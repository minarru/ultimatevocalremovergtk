# UVR Model Catalogue (TRvlvr + Politrees + extras + mvsepless)

Generated: 2026-08-25 15:44 UTC by `scripts/generate_models_catalogue.py`.

Regenerate after catalogue updates:

```bash
python scripts/generate_models_catalogue.py
```

Intent sources: catalogue label, yaml/hash metadata, Politrees model_data,
and [upseem/uvr5-cli-no-ui models.txt](https://github.com/upseem/uvr5-cli-no-ui/blob/main/models.txt)
(cached as `docs/model_intent_reference.tsv`).

## How to read this

- **Name intent** — from label, metadata, or community reference.
- **Backend focus** — catalogue helper summarizing primary/target; export is concept/route based.
- **Best result** — the stem users typically want from that model name.
- **Flags** — vocal/instrumental labelling mismatches (only when metadata resolved).

### Roformer `other` yaml quirk (not a bug)

Instrumental Mel-Band / BS models often use `target_instrument: other` with
`instruments: [other, vocals]`. That is a **2-stem vocal/instrumental** split.
The GUI should show **Vocals** / **Instrumental** for 2-stem yaml pairs, not Demucs Other.

## Source provenance

- Snapshot mode: `force`
- Source refreshed: extras, upstream, mvsepless, politrees
- Source stale: none
- Source failed: none
- Source upstream live: True
- Cache politrees: 1m old
- Cache community: 1m old
- Cache yaml: empty

## Summary

- Total catalogue entries: **485**
- Entries with resolved metadata: **483**
- Unknown intent remaining: **2**
- Flagged mismatches: **3**
- Unsupported mvsepless entries (omitted): **0**

## Models with unknown intent

| Family | Model | Metadata | Primary/Target |
| --- | --- | --- | --- |
| Apollo | Apollo — EDM Restoration Big · Essid | unavailable | — |
| Apollo | Apollo — EDM Restoration · Essid | unavailable | — |

## Quick reference (all models)

| Family | Model | Intent | Best result | Backend | Target | Flags |
| --- | --- | --- | --- | --- | --- | --- |
| VR Architecture | VR v4 — MGM High-End | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v4 — MGM Low-End A | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v4 — MGM Low-End B | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v4 — MGM Main | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — SP 2-Band 32 kHz 1 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — SP 2-Band 32 kHz 2 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — SP 3-Band 44.1 kHz | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — SP 4-Band 44.1 kHz 1 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — SP 4-Band 44.1 kHz 2 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — SP Mid 44.1 kHz 1 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — SP Mid 44.1 kHz 2 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — HP Wind Instrumental 17 | special_fx | no woodwinds (mix minus woodwinds) | two_stem | no woodwinds | — |
| VR Architecture | VR v5 — HP 1 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — HP 2 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — HP Vocals 3 | vocals | Vocals (+ Instrumental complement) | two_stem | Vocals | NAME says vocals but backend is not vocal-focused |
| VR Architecture | VR v5 — HP Vocals 4 | vocals | Vocals (+ Instrumental complement) | two_stem | Vocals | NAME says vocals but backend is not vocal-focused |
| VR Architecture | VR v5 — HP Karaoke 5 | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_instrumental_primary | Instrumental | — |
| VR Architecture | VR v5 — HP Karaoke 6 | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_instrumental_primary | Instrumental | — |
| VR Architecture | VR v5 — HP2 7 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — HP2 8 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — HP2 9 | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| VR Architecture | VR v5 — Karaoke BVE (4 Bands, SN, 44.1 kHz) 1 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| VR Architecture | VR v5 — De-Echo Aggressive · FoxJoy | special_fx | no echo (mix minus echo) | two_stem | no echo | — |
| VR Architecture | VR v5 — De-Echo Normal · FoxJoy | special_fx | no echo (mix minus echo) | two_stem | no echo | — |
| VR Architecture | VR v5 — De-Echo/DeReverb · FoxJoy | special_fx | no reverb (mix minus reverb) | two_stem | no reverb | — |
| VR Architecture | VR v5 — DeNoise · FoxJoy | special_fx | Noise (isolated noise stem) | two_stem | noise | — |
| VR Architecture | VR v5 — DeNoise Lite · FoxJoy | special_fx | Noise (isolated noise stem) | two_stem | noise | — |
| VR Architecture | VR v5 — DeReverb · Aufr33 & Jarredou | special_fx | Dry (dereverbbed signal) | two_stem | dry | — |
| MDX-Net | BandSplit Roformer — Guitar · Kimberley Xlance | specialty_stem | guitar, other | specialty_target:guitar | guitar | — |
| MDX-Net | BandSplit PolarFormer — 09-07-2026 (4 Stems) · Aname | multi_stem | Multi-stem: vocals, other, drums, bass | multi_stem | vocals | — |
| MDX-Net | BandSplit PolarFormer — Lazy Bat (4 Stems) · Aname | multi_stem | Multi-stem: vocals, other, drums, bass | multi_stem | vocals | — |
| MDX-Net | BandSplit PolarFormer — Instrumental/Vocals Duality Lazy Bat · Aname | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | vocals | — |
| MDX-Net | BandSplit PolarFormer — Karaoke · Lambda001 | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | lead | — |
| MDX-Net | BandSplit PolarFormer — Vocals · ZFTurbo | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer (4 Stems) · ZFTurbo | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | BandSplit Roformer (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | BandSplit Roformer — Bass Experimental · BeatLoo Labs | multi_stem | Multi-stem: bass, other | single_target:bass | bass | — |
| MDX-Net | BandSplit Roformer — Bass · Xlance | multi_stem | Multi-stem: bass, other | single_target:bass | bass | — |
| MDX-Net | BandSplit Roformer — Bowed Strings · Gilliaaan | instrument_target:bowed_strings | strings, other | two_stem | strings | — |
| MDX-Net | BandSplit Roformer — DeReverb (SDR 22.50) · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| MDX-Net | BandSplit Roformer — DeReverb 256-8 · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| MDX-Net | BandSplit Roformer — DeReverb 384-10 · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| MDX-Net | BandSplit Roformer — DeReverb Room · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| MDX-Net | BandSplit Roformer — Drums Duality · Gilliaaan | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | drums | — |
| MDX-Net | BandSplit Roformer — Drums Experimental · BeatLoo Labs | multi_stem | Multi-stem: drums, other | single_target:drums | drums | — |
| MDX-Net | BandSplit Roformer — Drums v1 · Xlance | multi_stem | Multi-stem: drums, other | single_target:drums | drums | — |
| MDX-Net | BandSplit Roformer — Drums v2 · Xlance | multi_stem | Multi-stem: drums, other | single_target:drums | drums | — |
| MDX-Net | BandSplit Roformer — FNF (Friday Night Funkin) Voices · MrDense67 | vocal_pair | Voices (single native output) | vocal_target | Voices | — |
| MDX-Net | BandSplit Roformer — FNF (Friday Night Funkin) Voices v2 · MrDense67 | vocal_pair | Voices (single native output) | vocal_target | Voices | — |
| MDX-Net | BandSplit Roformer — Instrumental Beta · neoculture | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Instrumental EXP Value Residual · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Instrumental FNO · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Instrumental HyperACE · Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | single_target:instrument | instrument | — |
| MDX-Net | BandSplit Roformer — Instrumental HyperACE v2 · Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | single_target:instrument | instrument | — |
| MDX-Net | BandSplit Roformer — Instrumental Large v2 · Unwa | instrumental | instrument (single native output) | single_target:instrument | instrument | — |
| MDX-Net | BandSplit Roformer — Instrumental Resurrection · Gabox | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Instrumental Resurrection · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Karaoke Inverted · GaboxR67 | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_instrumental_primary | other | — |
| MDX-Net | BandSplit Roformer — Karaoke · Anvuew | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | BandSplit Roformer — Karaoke · Becruily & Frazer | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | BandSplit Roformer — Karaoke · GaboxR67 | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | vocals | — |
| MDX-Net | BandSplit Roformer — Karaoke · GiantAILAB | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | vocals | — |
| MDX-Net | BandSplit Roformer — Keys · Xlance | instrument_target:keys | keys (single native output) | single_target:keys | keys | — |
| MDX-Net | BandSplit Roformer — Leap Instrumental · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Leap Vocals · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Leap XE (90 bands) Instrumental · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Leap XE (90 bands) Vocals · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Logic (6 Stems) · Chantrail | multi_stem | Multi-stem: bass, drums, other, vocals, guitar, pi… | multi_stem | bass | — |
| MDX-Net | BandSplit Roformer — Mag (3179) · Anvuew | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Mag · Anvuew | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Male/Female (ep 146) · Sucial | specialty_stem | male, female | specialty_two_stem | male | — |
| MDX-Net | BandSplit Roformer — Male/Female (ep 267) · Sucial | specialty_stem | male, female | specialty_two_stem | male | — |
| MDX-Net | BandSplit Roformer — Mega Full (53 Stems) · MVSep | multi_stem | Multi-stem: accordion, acoustic-guitar, back-vocal… | multi_stem | accordion | — |
| MDX-Net | BandSplit Roformer — Mega Accordion Only (53 Stems) · MVSep | instrument_target:accordion | accordion (single native output) | single_target:accordion | accordion | — |
| MDX-Net | BandSplit Roformer — Mega Acoustic Guitar Only (53 Stems) · MVSep | instrument_target:acoustic_guitar | acoustic-guitar (single native output) | single_target:acoustic-guitar | acoustic-guitar | — |
| MDX-Net | BandSplit Roformer — Mega Backing Vocals Only (53 Stems) · MVSep | specialty_stem | back-vocal, other | single_target:back-vocal | back-vocal | — |
| MDX-Net | BandSplit Roformer — Mega Banjo Only (53 Stems) · MVSep | instrument_target:banjo | banjo (single native output) | single_target:banjo | banjo | — |
| MDX-Net | BandSplit Roformer — Mega Bass Only (53 Stems) · MVSep | multi_stem | Multi-stem: bass, other | single_target:bass | bass | — |
| MDX-Net | BandSplit Roformer — Mega Bassoon Only (53 Stems) · MVSep | multi_stem | Multi-stem: bassoon, other | single_target:bassoon | bassoon | — |
| MDX-Net | BandSplit Roformer — Mega Bells Only (53 Stems) · MVSep | instrument_target:bells | bells (single native output) | single_target:bells | bells | — |
| MDX-Net | BandSplit Roformer — Mega Bowed Strings Only (53 Stems) · MVSep | instrument_target:bowed_strings | bowed_strings (single native output) | single_target:bowed_strings | bowed_strings | — |
| MDX-Net | BandSplit Roformer — Mega Brass Only (53 Stems) · MVSep | instrument_target:brass | brass (single native output) | single_target:brass | brass | — |
| MDX-Net | BandSplit Roformer — Mega Cello Only (53 Stems) · MVSep | instrument_target:cello | cello (single native output) | single_target:cello | cello | — |
| MDX-Net | BandSplit Roformer — Mega Clarinet Only (53 Stems) · MVSep | instrument_target:clarinet | clarinet (single native output) | single_target:clarinet | clarinet | — |
| MDX-Net | BandSplit Roformer — Mega Congas Only (53 Stems) · MVSep | instrument_target:congas | congas (single native output) | single_target:congas | congas | — |
| MDX-Net | BandSplit Roformer — Mega Digital Piano Only (53 Stems) · MVSep | instrument_target:digital_piano | digital-piano (single native output) | single_target:digital-piano | digital-piano | — |
| MDX-Net | BandSplit Roformer — Mega Dobro Only (53 Stems) · MVSep | instrument_target:dobro | dobro (single native output) | single_target:dobro | dobro | — |
| MDX-Net | BandSplit Roformer — Mega Double Bass Only (53 Stems) · MVSep | multi_stem | Multi-stem: double-bass, other | single_target:double-bass | double-bass | — |
| MDX-Net | BandSplit Roformer — Mega Drums Only (53 Stems) · MVSep | multi_stem | Multi-stem: drums, other | single_target:drums | drums | — |
| MDX-Net | BandSplit Roformer — Mega Electric Guitar Only (53 Stems) · MVSep | instrument_target:electric_guitar | electric-guitar (single native output) | single_target:electric-guitar | electric-guitar | — |
| MDX-Net | BandSplit Roformer — Mega Flute Only (53 Stems) · MVSep | instrument_target:flute | flute (single native output) | single_target:flute | flute | — |
| MDX-Net | BandSplit Roformer — Mega French Horn Only (53 Stems) · MVSep | instrument_target:french_horn | french-horn (single native output) | single_target:french-horn | french-horn | — |
| MDX-Net | BandSplit Roformer — Mega Glockenspiel Only (53 Stems) · MVSep | instrument_target:glockenspiel | glockenspiel (single native output) | single_target:glockenspiel | glockenspiel | — |
| MDX-Net | BandSplit Roformer — Mega Guitar Only (53 Stems) · MVSep | instrument_target:guitar | guitar (single native output) | specialty_target:guitar | guitar | — |
| MDX-Net | BandSplit Roformer — Mega Harmonica Only (53 Stems) · MVSep | instrument_target:harmonica | harmonica (single native output) | single_target:harmonica | harmonica | — |
| MDX-Net | BandSplit Roformer — Mega Harp Only (53 Stems) · MVSep | instrument_target:harp | harp (single native output) | single_target:harp | harp | — |
| MDX-Net | BandSplit Roformer — Mega Harpsichord Only (53 Stems) · MVSep | instrument_target:harpsichord | harpsichord (single native output) | single_target:harpsichord | harpsichord | — |
| MDX-Net | BandSplit Roformer — Mega Hi-Hat Only (53 Stems) · MVSep | instrument_target:hh | hh (single native output) | single_target:hh | hh | — |
| MDX-Net | BandSplit Roformer — Mega Keys Only (53 Stems) · MVSep | instrument_target:keys | keys (single native output) | single_target:keys | keys | — |
| MDX-Net | BandSplit Roformer — Mega Kick Only (53 Stems) · MVSep | instrument_target:kick | kick (single native output) | single_target:kick | kick | — |
| MDX-Net | BandSplit Roformer — Mega Lead Vocals Only (53 Stems) · MVSep | vocals | lead-vocal (single native output) | vocal_target | lead-vocal | — |
| MDX-Net | BandSplit Roformer — Mega Mandolin Only (53 Stems) · MVSep | instrument_target:mandolin | mandolin (single native output) | single_target:mandolin | mandolin | — |
| MDX-Net | BandSplit Roformer — Mega Marimba Only (53 Stems) · MVSep | instrument_target:marimba | marimba (single native output) | single_target:marimba | marimba | — |
| MDX-Net | BandSplit Roformer — Mega Oboe Only (53 Stems) · MVSep | instrument_target:oboe | oboe (single native output) | single_target:oboe | oboe | — |
| MDX-Net | BandSplit Roformer — Mega Organ Only (53 Stems) · MVSep | instrument_target:organ | organ (single native output) | single_target:organ | organ | — |
| MDX-Net | BandSplit Roformer — Mega Percussion Only (53 Stems) · MVSep | instrument_target:percussion | percussion (single native output) | single_target:percussion | percussion | — |
| MDX-Net | BandSplit Roformer — Mega Piano Only (53 Stems) · MVSep | instrument_target:piano | piano (single native output) | single_target:piano | piano | — |
| MDX-Net | BandSplit Roformer — Mega Saxophone Only (53 Stems) · MVSep | instrument_target:saxophone | saxophone (single native output) | single_target:saxophone | saxophone | — |
| MDX-Net | BandSplit Roformer — Mega Sitar Only (53 Stems) · MVSep | instrument_target:sitar | sitar (single native output) | single_target:sitar | sitar | — |
| MDX-Net | BandSplit Roformer — Mega Snare Only (53 Stems) · MVSep | instrument_target:snare | snare (single native output) | single_target:snare | snare | — |
| MDX-Net | BandSplit Roformer — Mega Strings Only (53 Stems) · MVSep | instrument_target:strings | strings (single native output) | single_target:strings | strings | — |
| MDX-Net | BandSplit Roformer — Mega Synth Only (53 Stems) · MVSep | instrument_target:synth | synth (single native output) | single_target:synth | synth | — |
| MDX-Net | BandSplit Roformer — Mega Tambourine Only (53 Stems) · MVSep | instrument_target:tambourine | tambourine (single native output) | single_target:tambourine | tambourine | — |
| MDX-Net | BandSplit Roformer — Mega Timpani Only (53 Stems) · MVSep | instrument_target:timpani | timpani (single native output) | single_target:timpani | timpani | — |
| MDX-Net | BandSplit Roformer — Mega Toms Only (53 Stems) · MVSep | instrument_target:toms | toms (single native output) | single_target:toms | toms | — |
| MDX-Net | BandSplit Roformer — Mega Triangle Only (53 Stems) · MVSep | instrument_target:triangle | triangle (single native output) | single_target:triangle | triangle | — |
| MDX-Net | BandSplit Roformer — Mega Trombone Only (53 Stems) · MVSep | instrument_target:trombone | trombone (single native output) | single_target:trombone | trombone | — |
| MDX-Net | BandSplit Roformer — Mega Trumpet Only (53 Stems) · MVSep | instrument_target:trumpet | trumpet (single native output) | single_target:trumpet | trumpet | — |
| MDX-Net | BandSplit Roformer — Mega Tuba Only (53 Stems) · MVSep | instrument_target:tuba | tuba (single native output) | single_target:tuba | tuba | — |
| MDX-Net | BandSplit Roformer — Mega Ukulele Only (53 Stems) · MVSep | instrument_target:ukulele | ukulele (single native output) | single_target:ukulele | ukulele | — |
| MDX-Net | BandSplit Roformer — Mega Viola Only (53 Stems) · MVSep | instrument_target:viola | viola (single native output) | single_target:viola | viola | — |
| MDX-Net | BandSplit Roformer — Mega Violin Only (53 Stems) · MVSep | instrument_target:violin | violin (single native output) | single_target:violin | violin | — |
| MDX-Net | BandSplit Roformer — Mega Vocals Only (53 Stems) · MVSep | vocals | Vocals (complement = Instrumental) | vocal_target | vocal | — |
| MDX-Net | BandSplit Roformer — Mega Wind Only (53 Stems) · MVSep | instrument_target:wind | wind (single native output) | single_target:wind | wind | — |
| MDX-Net | BandSplit Roformer — Mega Wind Chimes Only (53 Stems) · MVSep | instrument_target:wind_chimes | wind-chimes (single native output) | single_target:wind-chimes | wind-chimes | — |
| MDX-Net | BandSplit Roformer — Mega Woodwind Only (53 Stems) · MVSep | instrument_target:woodwind | woodwind (single native output) | single_target:woodwind | woodwind | — |
| MDX-Net | BandSplit Roformer — Mid-Side v1 · Gilliaaan | spatial | center (single native output) | single_target:center | center | — |
| MDX-Net | BandSplit Roformer — Mid-Side v2 · Gilliaaan | spatial | center (single native output) | single_target:center | center | — |
| MDX-Net | BandSplit Roformer — Orchestra v1 · Xlance | instrument_target:orch | orch (single native output) | single_target:orch | orch | — |
| MDX-Net | BandSplit Roformer — Orchestra v2 · Xlance | instrument_target:orch | orch (single native output) | single_target:orch | orch | — |
| MDX-Net | BandSplit Roformer — Other · ViperX | vocal_pair | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | BandSplit Roformer — Percussion v1 · Xlance | instrument_target:percussion | percussion (single native output) | single_target:percussion | percussion | — |
| MDX-Net | BandSplit Roformer — Percussion v2 · Xlance | instrument_target:percussion | percussion (single native output) | single_target:percussion | percussion | — |
| MDX-Net | BandSplit Roformer — Resurrection v2 (Quality Test) · Unwa | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — SW | multi_stem | Multi-stem: bass, drums, other, vocals, guitar, pi… | multi_stem | bass | — |
| MDX-Net | BandSplit Roformer — SW Fixed · Jarredou | multi_stem | Multi-stem: bass, drums, other, vocals, guitar, pi… | multi_stem | bass | — |
| MDX-Net | BandSplit Roformer — SpeechSep · AliceN | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Synth v1 · Xlance | instrument_target:synth | synth (single native output) | single_target:synth | synth | — |
| MDX-Net | BandSplit Roformer — Synth v2 · Xlance | instrument_target:synth | synth (single native output) | single_target:synth | synth | — |
| MDX-Net | BandSplit Roformer — Vocals (SDR 12.96) · ViperX | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | BandSplit Roformer — Vocals (SDR 12.97) · ViperX | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | BandSplit Roformer — Vocals Fine-Tuned v1 · Anvuew | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals HyperACE v2 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals Large v1 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals Resurrection · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals Revive v1 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals Revive v2 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals Revive v3e · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals · Anvuew | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | BandSplit Roformer — Vocals v1 · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals v2 · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | BandSplit Roformer — Vocals · Xlance | vocal_pair | vox (single native output) | vocal_target | vox | — |
| MDX-Net | BandSplit Roformer — Siamese Vocals · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Bandit | Bandit — Last Checkpoint · ZFTurbo | multi_stem | Multi-stem: speech, music, effects | multi_stem | speech | — |
| Bandit | Bandit — Plus (ep 30) · ZFTurbo | multi_stem | Multi-stem: speech, music, effects | multi_stem | speech | — |
| Bandit | Bandit — Plus (ep 57) · ZFTurbo | multi_stem | Multi-stem: speech, music, effects | multi_stem | speech | — |
| Bandit | Bandit — Plus (ep 63) · ZFTurbo | multi_stem | Multi-stem: speech, music, effects | multi_stem | speech | — |
| Bandit | Bandit — Cinematic Bandit Plus · kwatcharasupat | multi_stem | Multi-stem: Speech, Music, Effects | multi_stem | Speech | — |
| Bandit | Bandit — Cinematic Bandit v2 Multilang · kwatcharasupat | multi_stem | Multi-stem: Speech, Music, Sfx | multi_stem | Speech | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental Full 292 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental 187 Beta | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental 82 Beta | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental 90 Beta | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Main 340 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net ONNX | MDX-Net — UVR Main 390 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net ONNX | MDX-Net — UVR Main 406 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net ONNX | MDX-Net — UVR Main 427 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net ONNX | MDX-Net — UVR Main 438 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net ONNX | MDX-Net — Kim Instrumental | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net — Kim Vocals 1 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — Kim Vocals 2 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — Reverb HQ · FoxJoy | special_fx | Reverb (isolated reverb stem) | special_fx_primary:reverb | reverb | — |
| MDX-Net ONNX | MDX-Net — UVR 1 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — UVR 2 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — UVR 3 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — UVR Crowd HQ 1 · Aufr33 | special_fx | no crowd (mix minus crowd) | special_fx_primary:no crowd | no crowd | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental 1 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental 2 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental 3 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental HQ 1 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental HQ 2 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental HQ 3 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental HQ 4 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental HQ 5 | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Instrumental Main | instrumental | Instrumental (complement = Vocals) | instrumental_target | instrumental | — |
| MDX-Net ONNX | MDX-Net — UVR Karaoke | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — UVR Karaoke 2 | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_instrumental_primary | other | — |
| MDX-Net ONNX | MDX-Net — UVR Main | dual_voc_inst | Vocals or Instrumental — both are first-class 2-st… | vocal_target | vocals | — |
| MDX-Net ONNX | MDX-Net — UVR Vocals Fine-Tuned | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net ONNX | MDX-Net — UVR 9482 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — KUIELAB A Bass | multi_stem | Kuielab Demucs bass stem (single 4-stem component) | demucs_component:bass | bass | — |
| MDX-Net ONNX | MDX-Net — KUIELAB A Drums | multi_stem | Kuielab Demucs drums stem (single 4-stem component… | demucs_component:drums | drums | — |
| MDX-Net ONNX | MDX-Net — KUIELAB A Other | multi_stem | Kuielab Demucs other stem (single 4-stem component… | demucs_component:other | other | — |
| MDX-Net ONNX | MDX-Net — KUIELAB A Vocals | multi_stem | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net — KUIELAB B Bass | multi_stem | Kuielab Demucs bass stem (single 4-stem component) | demucs_component:bass | bass | — |
| MDX-Net ONNX | MDX-Net — KUIELAB B Drums | multi_stem | Kuielab Demucs drums stem (single 4-stem component… | demucs_component:drums | drums | — |
| MDX-Net ONNX | MDX-Net — KUIELAB B Other | multi_stem | Kuielab Demucs other stem (single 4-stem component… | demucs_component:other | other | — |
| MDX-Net ONNX | MDX-Net — KUIELAB B Vocals | multi_stem | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net | MDX23C — Small (4 Stems) · KUIELAB | multi_stem | Vocals (+ Instrumental complement) | multi_stem | vocals | — |
| MDX-Net | MDX23C (4 Stems) · KUIELAB | multi_stem | Vocals (+ Instrumental complement) | multi_stem | vocals | — |
| MDX-Net | MDX23C (4 Stems) · ZFTurbo | multi_stem | Multi-stem: vocals, bass, drums, other | multi_stem | vocals | — |
| MDX-Net | MDX23C — 8K FFT Instrumental/Vocals HQ v1 | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | Vocals | — |
| MDX-Net | MDX23C — 8K FFT Instrumental/Vocals HQ v2 | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | Vocals | — |
| MDX-Net | MDX23C — DrumSep (5 Stems) · Aufr33 & Jarredou | multi_stem | Multi-stem: kick, snare, toms, hh, cymbals | multi_stem | kick | — |
| MDX-Net | MDX23C — DrumSep (6 Stems) · Aufr33 & Jarredou | multi_stem | Multi-stem: kick, snare, toms, hh, ride, crash | multi_stem | kick | — |
| MDX-Net | MDX23C — Instrumental/Vocals HQ · ZFTurbo | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | vocals | — |
| MDX-Net | MDX23C — Mid-Side · WesleyR36 | spatial | similarity (single native output) | specialty_target:similarity | similarity | — |
| MDX-Net | MDX23C — Mid-Side v1 · Gilliaaan | spatial | wide (single native output) | single_target:wide | wide | — |
| MDX-Net | MDX23C — Mid-Side v2e · Gilliaaan | spatial | center, wide | two_stem | center | — |
| MDX23C | MDX23C — 8K FFT Instrumental/Vocals HQ 2 | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | vocal_primary | Vocals | — |
| MDX23C | MDX23C — DeReverb · Aufr33 & Jarredou | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| MDX23C | MDX23C — DrumSep · Aufr33 & Jarredou | multi_stem | Multi-stem: kick, snare, toms, hh, ride, crash | multi_stem | kick | — |
| MDX23C | MDX23C — Phantom Centre Extraction · WesleyR36 | specialty_stem | Similarity, Difference | specialty_target:Similarity | Similarity | — |
| MDX23C | MDX23C — 8K FFT Instrumental/Vocals HQ | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | vocal_primary | Vocals | — |
| MDX23C | MDX23C — D1581 | vocals | Vocals (+ Instrumental complement) | two_stem | Vocals | NAME says vocals but backend is not vocal-focused |
| MDX-Net | MDX23C — Orchestra Experimental · Verosment | instrument_target:orch | orch (single native output) | single_target:orch | orch | — |
| MDX-Net | MDX23C — SFX Splitter · Jasper | multi_stem | Multi-stem: foreground, background | two_stem | foreground | — |
| MDX-Net | MDX23C — SFX · Jasper | multi_stem | Multi-stem: foreground, background | two_stem | foreground | — |
| MDX-Net | MDX23C — Vocals · KUIELAB | multi_stem | Vocals (+ Instrumental complement) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Large (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | MelBand Roformer — XL (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | MelBand Roformer — Large v2 (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | MelBand Roformer — Ambiance · jazzpear | vocal_pair | ambience (single native output) | single_target:ambience | ambience | — |
| MDX-Net | MelBand Roformer — BGM · Jasper | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Karaoke BVE · Gonzaluigi | specialty_stem | Lead, Back | specialty_target:Lead | Lead | — |
| MDX-Net | MelBand Roformer — Big Beta v1 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Big Beta v2 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Big Beta v3 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Big Beta v4 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Big Beta v6 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Big Beta v6x · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Big Beta v7 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Big SYHFT v1 Fast · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — DeBigReverb · Sucial | removal:reverb | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| MDX-Net | MelBand Roformer — DeNoise Aggressive · Aufr33 | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| MDX-Net | MelBand Roformer — DeNoise · Yuluoye | special_fx | other (post-processing stem) | special_fx_target:dry | other | — |
| MDX-Net | MelBand Roformer — DeNoiser Children 16 kHz · Phaedrus33 | special_fx | speech (post-processing stem) | single_target:speech | speech | — |
| MDX-Net | MelBand Roformer — DeUX · Becruily | vocal_pair | Vocals (+ Instrumental complement) | two_stem | Vocals | — |
| MDX-Net | MelBand Roformer — DeNoise DeBleed · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Duet · Dry Paint Dealer Undr | vocal_pair | singer_1, singer_2 | two_stem | singer_1 | — |
| MDX-Net | MelBand Roformer — Explosions · jazzpear | vocal_pair | explosions (single native output) | single_target:explosions | explosions | — |
| MDX-Net | MelBand Roformer — Fighting · jazzpear | vocal_pair | fighting (single native output) | single_target:fighting | fighting | — |
| MDX-Net | MelBand Roformer — Foley · jazzpear | vocal_pair | foley (single native output) | single_target:foley | foley | — |
| MDX-Net | MelBand Roformer — Footsteps · jazzpear | vocal_pair | footsteps (single native output) | single_target:footsteps | footsteps | — |
| MDX-Net | MelBand Roformer — General · jazzpear | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Guitar · chenCFD | specialty_stem | guitar, others | specialty_target:guitar | guitar | — |
| MDX-Net | MelBand Roformer — Hybrid Arch · Aname | vocal_pair | Vocals (+ Instrumental complement) | two_stem | vocals | — |
| MDX-Net | MelBand Roformer — Instrumental Rifforge · Mesk | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Instrumental VFX · neoculture | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental/Vocals Duality v1 · Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | Vocals | — |
| MDX-Net | MelBand Roformer — Instrumental/Vocals Duality v2 · Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | Vocals | — |
| MDX-Net | MelBand Roformer — Instrumental Bv1 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Bv2 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Bv3 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Flowers v10 · GaboxR67 | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Instrumental Fv1 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv10 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv2 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv3 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv4 Noise · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv4 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv5 Noise · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv5 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv6 Noise · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv6 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv7 Noise · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv7 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv7+ · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv7z · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv8 · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv8b · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv9 · GaboxR67 [mbr_instfv9_2_gabox] | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental Fv9 · GaboxR67 [mbr_instfv9_gabox] | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental FvX · GaboxR67 | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental · Becruily [mbr_guitar_becruily] | instrumental | Guitar (single native output) | specialty_target:Guitar | Guitar | — |
| MDX-Net | MelBand Roformer — Instrumental · Becruily [mbr_inst_becruily] | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental (SDR 16.52) · Essid | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental (SDR 16.81) · Essid | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| MDX-Net | MelBand Roformer — Instrumental v1 · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Instrumental v1+ · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Instrumental v1e Plus · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Instrumental v1e · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Instrumental v2 · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Karaoke 25-02-2025 · GaboxR67 | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_unknown_primary | karaoke | — |
| MDX-Net | MelBand Roformer — Karaoke 28-02-2025 · GaboxR67 | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_unknown_primary | karaoke | — |
| MDX-Net | MelBand Roformer — Karaoke Fusion Aggressive · Gonzaluigi [mbr_karaoke_fusion2_aggr_gonzaluigi] | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | MelBand Roformer — Karaoke Fusion Aggressive · Gonzaluigi [mbr_karaoke_fusion_aggr_gonzaluigi] | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | MelBand Roformer — Karaoke Fusion Total · Gonzaluigi | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | MelBand Roformer — Karaoke Fusion · Gonzaluigi | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | MelBand Roformer — Karaoke Small · GaboxR67 & Aufr33 | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | MelBand Roformer — Karaoke v1 · GaboxR67 | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | MelBand Roformer — Karaoke v2 · GaboxR67 | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net | MelBand Roformer — Kim Fine-Tuned v1 · Aname | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Kim Fine-Tuned v1 · Unwa | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Kim Fine-Tuned v2 Fullness · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Kim Fine-Tuned v2 · Aname | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Kim Fine-Tuned v3 · Aname | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Kim Fine-Tuned v3 Preview · Unwa | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Lead Vocals DeReverb · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Lead-Rhythm Guitar · listra92 | specialty_stem | Lead, Rhythm | specialty_target:Lead | Lead | — |
| MDX-Net | MelBand Roformer — Merged Beta v1 · SYH99999 | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Metal Instrumental Preview · Mesk | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | MelBand Roformer — Mid-Side · Gilliaaan | spatial | mid, side | two_stem | mid | — |
| MDX-Net | MelBand Roformer — Musicless · Jasper | multi_stem | Multi-stem: nomusic, music | single_target:nomusic | nomusic | — |
| MDX-Net | MelBand Roformer — Percussion Experimental · yolkispalkis | instrument_target:percussion | percussions (single native output) | single_target:percussions | percussions | — |
| MDX-Net | MelBand Roformer — SYHFT B1 1 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — SYHFT B1 2 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — SYHFT B1 3 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — SYHFT v1 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — SYHFT v2 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — SYHFT v2.5 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — SYHFT v3 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Scratch Large · Aname | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Small v1 · Unwa | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — SpeechSep · AliceN | multi_stem | Multi-stem: vocals, other | two_stem | vocals | — |
| MDX-Net | MelBand Roformer — Super Big DeReverb · Sucial | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| MDX-Net | MelBand Roformer — Toon · jazzpear | vocal_pair | anime (single native output) | single_target:anime | anime | — |
| MDX-Net | MelBand Roformer — Vocals Big Beta v5e · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv1 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv2 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv3 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv4 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv5 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv6 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv7 Beta 1 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv7 Beta 2 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv7 Beta 3 · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals Fv7 Final · GaboxR67 | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| MDX-Net | MelBand Roformer — Vocals · ViperX | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Vocals · ZFTurbo | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| MDX-Net | MelBand Roformer — Xeno · DrYound3r | vocal_pair | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer — Drum/Bass Separation (SDR 10.53) · ViperX | drum_bass_sep | no drum-bass (drum/bass separation; complement = D… | special_fx_primary:no drum-bass | no drum-bass | — |
| Roformer | BandSplit Roformer — ViperX 12.96 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| Roformer | BandSplit Roformer — ViperX 12.97 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| Roformer | BandSplit Roformer — Fine-Tuned (4 Stems) · SYH99999 | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | BandSplit Roformer — Chorus Male/Female · Sucial | specialty_stem | male, female | specialty_two_stem | male | — |
| Roformer | BandSplit Roformer — DeReverb · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| Roformer | BandSplit Roformer — FNO · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | BandSplit Roformer — HyperACE Instrumental · Unwa | instrumental | instrument (single native output) | single_target:instrument | instrument | — |
| Roformer | BandSplit Roformer — HyperACE v2 Instrumental · Unwa | instrumental | instrument (single native output) | single_target:instrument | instrument | — |
| Roformer | BandSplit Roformer — HyperACE v2 Vocals · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer — Instrumental EXP Value Residual · Unwa [BS_Inst_EXP_VRL] | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | BandSplit Roformer — Karaoke Frazer · Becruily | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | BandSplit Roformer — Male/Female · Aufr33 | specialty_stem | male, female | specialty_two_stem | male | — |
| Roformer | BandSplit Roformer — Resurrection Instrumental · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | BandSplit Roformer — Resurrection Vocals · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer — Revive · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer — Revive v2 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer — Revive v3 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer — SW · Jarredou | multi_stem | Multi-stem: bass, drums, other, vocals, guitar, pi… | multi_stem | bass | — |
| Roformer | BandSplit Roformer — Vocals · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals (SDR 11.44) · ViperX | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Kim Big Beta v4 Fine-Tuned · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Big Beta v5e Fine-Tuned · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Big Beta v6 Fine-Tuned · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Big Beta v6x Fine-Tuned · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Big SYHFT v1 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Fine-Tuned · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Fine-Tuned v2 Bleedless · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Fine-Tuned v2 · Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Instrumental v1 · Unwa | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| Roformer | MelBand Roformer — Kim Instrumental v2 · Unwa | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| Roformer | MelBand Roformer — Kim Instrumental v1e Plus · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | MelBand Roformer — Kim Instrumental v1e · Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | MelBand Roformer — Kim Instrumental/Vocals Duality v1 · Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Kim Instrumental/Vocals Duality v2 · Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Kim SYHFT · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim SYHFT v2 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim SYHFT v2.5 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim SYHFT v3 · SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Vocals Fullness v1 · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Vocals Fullness v2 · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Vocals v1 · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Vocals v2 · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Kim Vocals v3 · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Fine-Tuned Large v1 (4 Stems) · SYH99999 | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer — Fine-Tuned Large v2 (4 Stems) · SYH99999 | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer — Large v1 (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer — XL v1 (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer — Aspiration Less Aggressive · Sucial | specialty_stem | aspiration, other | specialty_two_stem | aspiration | — |
| Roformer | MelBand Roformer — Aspiration · Sucial | specialty_stem | aspiration, other | specialty_two_stem | aspiration | — |
| Roformer | MelBand Roformer — Karaoke BVE · Gonza | specialty_stem | Lead, Back | specialty_target:Lead | Lead | — |
| Roformer | MelBand Roformer — Bleed Suppressor v1 · Unwa & 97chris | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Crowd · Aufr33 & ViperX | specialty_stem | crowd, other | specialty_target:crowd | crowd | — |
| Roformer | MelBand Roformer — DeReverb Big · Sucial | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| Roformer | MelBand Roformer — DeReverb Less Aggressive · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| Roformer | MelBand Roformer — DeReverb Mono · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| Roformer | MelBand Roformer — DeReverb Super Big · Sucial | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| Roformer | MelBand Roformer — DeReverb · Anvuew | special_fx | No reverb (dereverbbed signal) | special_fx_target:noreverb | noreverb | — |
| Roformer | MelBand Roformer — DeReverb-Echo Fused · Sucial | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| Roformer | MelBand Roformer — DeReverb-Echo · Sucial | special_fx | Dry (dereverbbed signal) | two_stem | dry | — |
| Roformer | MelBand Roformer — DeReverb-Echo v2 · Sucial | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| Roformer | MelBand Roformer — DeNoise Aggr · Aufr33 | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| Roformer | MelBand Roformer — DeNoise · Aufr33 | special_fx | Dry (dereverbbed signal) | special_fx_target:dry | dry | — |
| Roformer | MelBand Roformer — Duality v1 · Aname | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Guitar · Becruily | specialty_stem | Guitar, Other | specialty_target:Guitar | Guitar | — |
| Roformer | MelBand Roformer — Instrumental Bleedless v1 · Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Bleedless v2 · Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental DeNoise-DeBleed · Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v1 · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v2 · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v3 · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v4 Noise · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v5 Noise · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v5 · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v6 Noise · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v6 · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v7 Noise · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v7 · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness v8 · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental Fullness vX · Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental · Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental · Becruily | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental v1 · Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental v2 · Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Instrumental v3 · Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer — Karaoke Fusion Aggressive · Gonza | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Karaoke Fusion Aggressive v2 · Gonza | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Karaoke Fusion Standard · Gonza | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Karaoke Fusion Total · Gonza | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Karaoke · Aufr33 & ViperX | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Karaoke · Gabox | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Karaoke Beta · Gabox | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Karaoke · Becruily | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| Roformer | MelBand Roformer — Small · Aname | vocal_pair | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| Roformer | MelBand Roformer — Vocals Fullness · Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Vocals Fullness v1 · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals Fullness v2 · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals Fullness v3 · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals Fullness v4 · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals Fullness v5 · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals Fullness v6 · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals · Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer — Vocals · Kimberley Jensen | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Vocals · Becruily | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer — Instrumental Metal Preview · Mesk | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| MDX-Net | SCNet — Huge v1 (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet — XL (4 Stems) · StarryTong | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet — XL (4 Stems) · ZFTurbo | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet (4 Stems) · ZFTurbo | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet — ChoirSep · Dry Paint Dealer Undr | multi_stem | Multi-stem: alto, bass, soprano, tenor | multi_stem | alto | — |
| MDX-Net | SCNet — Large Jazz model · Joris Vaneyghen | multi_stem | Multi-stem: drums, bass, piano, other | multi_stem | drums | — |
| MDX-Net | SCNet — Masked Small (4 Stems) · ZFTurbo | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet — Masked XL IHF (4 Stems) · ZFTurbo | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet — Masked ChoirSep · Dry Paint Dealer Undr | multi_stem | Multi-stem: soprano, alto, tenor, bass | multi_stem | soprano | — |
| MDX-Net | SCNet — Mid-Side v2 · Gilliaaan | multi_stem | Multi-stem: center, wide | two_stem | center | — |
| MDX-Net | SCNet — Surround · Jasper | multi_stem | Multi-stem: LRF, LFE, LRS, CEN | multi_stem | LRF | — |
| MDX-Net | SCNet — Tran (4 Stems) · ZFTurbo | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet — XL IHF (4 Stems) · ZFTurbo | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| MDX-Net | SCNet — XL Jazz model · Joris Vaneyghen | multi_stem | Multi-stem: drums, bass, piano, other | multi_stem | drums | — |
| SCNet | SCNet — Huge Bleedless (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| SCNet | SCNet — Huge Fullness (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| SCNet | SCNet — Huge Strong Fullness (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| SCNet | SCNet — Huge v1.2 (4 Stems) · Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| SCNet | SCNet — Large (4 Stems) | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| SCNet | SCNet — Large (4 Stems) · StarryTong | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| SCNet | SCNet — MUSDB18 (4 Stems) · StarryTong | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| SCNet | SCNet — XL (4 Stems) | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| Demucs | Demucs v1 — Time-Domain | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1 — Time-Domain Extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1 — Light | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1 — Light Extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1 — Conv-TasNet | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1 — Conv-TasNet Extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2 — Time-Domain | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2 — Time-Domain 48 kHz HQ | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2 — Time-Domain Extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2 — Unit Test | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2 — Conv-TasNet | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2 — Conv-TasNet Extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3 — UVR Model (2 Stems) | dual_voc_inst | 2-stem: instrumental + vocals (user picks focus) | two_stem |  | — |
| Demucs | Demucs v3 — MDX | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3 — MDX Extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3 — MDX Extra Quantized | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3 — MDX Quantized | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3 — Repro MDX A | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3 — Repro MDX A Hybrid Only | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3 — Repro MDX A Time-Domain Only | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4 — Hybrid Demucs MMI | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4 — Hybrid Transformer | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4 — Hybrid Transformer (6 Stems) | multi_stem | 6-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4 — Hybrid Transformer Fine-Tuned | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Apollo | Apollo — EDM Restoration Big · Essid | unknown | unknown | unknown |  | — |
| Apollo | Apollo — EDM Restoration · Essid | unknown | unknown | unknown |  | — |

## Karaoke models

Karaoke models differ by architecture: VR HP-Karaoke uses **Instrumental** as
`primary_stem`; MDX-Net Karaoke uses **Vocals** with `is_karaoke: true`.
Roformer karaoke yamls typically target **vocals** (lead) with instrumental complement.

| Model | Primary | Karaoke flag | Best result |
| --- | --- | --- | --- |
| VR v5 — HP Karaoke 5 | Instrumental | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| VR v5 — HP Karaoke 6 | Instrumental | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| BandSplit PolarFormer — Karaoke · Lambda001 | lead | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| BandSplit Roformer — Karaoke Inverted · GaboxR67 | other | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| BandSplit Roformer — Karaoke · Anvuew | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| BandSplit Roformer — Karaoke · Becruily & Frazer | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| BandSplit Roformer — Karaoke · GaboxR67 | vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| BandSplit Roformer — Karaoke · GiantAILAB | vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MDX-Net — UVR Karaoke | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MDX-Net — UVR Karaoke 2 | Instrumental | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer — Karaoke 25-02-2025 · GaboxR67 | karaoke | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer — Karaoke 28-02-2025 · GaboxR67 | karaoke | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer — Karaoke Fusion Aggressive · Gonzaluigi [mbr_karaoke_fusion2_aggr_gonzaluigi] | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Fusion Aggressive · Gonzaluigi [mbr_karaoke_fusion_aggr_gonzaluigi] | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Fusion Total · Gonzaluigi | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Fusion · Gonzaluigi | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Small · GaboxR67 & Aufr33 | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke v1 · GaboxR67 | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke v2 · GaboxR67 | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| BandSplit Roformer — Karaoke Frazer · Becruily | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Fusion Aggressive · Gonza | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Fusion Aggressive v2 · Gonza | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Fusion Standard · Gonza | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Fusion Total · Gonza | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke · Aufr33 & ViperX | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke · Gabox | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke Beta · Gabox | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MelBand Roformer — Karaoke · Becruily | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |

## Instrumental models with yaml stem `other`

These models are **instrumental-first** in practice. The training yaml names the
native output `other` (not `Instrumental`). Backend `primary_stem` is therefore
`other`, which previously showed as Demucs-style “Other” in the GUI. Relabel to
**Vocals** / **Instrumental** (yaml `other` is the backing track).

| Model | Config | Instruments | Best result |
| --- | --- | --- | --- |
| BandSplit Roformer — Instrumental Beta · neoculture | bs_neo_inst_beta_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — Instrumental EXP Value Residual · Unwa | bs_inst_exp_vlp_unwa_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — Instrumental FNO · Unwa | bs_inst_fno_unwa_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — Instrumental Resurrection · Gabox | bs_resurrection_inst_gabox_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — Instrumental Resurrection · Unwa | bs_resurrection_inst_unwa_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — Leap Instrumental · Unwa | bs_leap_inst_unwa_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — Leap XE (90 bands) Instrumental · Unwa | bs_leap_xe_inst_unwa_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental Rifforge · Mesk | mbr_inst_rifforge_meskvlla33_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental Flowers v10 · GaboxR67 | mbr_instflowersv10_gabox_config.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental v1 · Unwa | mbr_inst1_unwa_config.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental v1+ · Unwa | mbr_inst1+_unwa_config.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental v1e Plus · Unwa | mbr_inst1e+_unwa_config.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental v1e · Unwa | mbr_inst1e_unwa_config.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental v2 · Unwa | mbr_inst2_unwa_config.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Metal Instrumental Preview · Mesk | mbr_inst_metal_prev_meskvlla33_config.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — FNO · Unwa | config_BandSplit-Roformer_FNO_by-Unwa.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer — Resurrection Instrumental · Unwa | config_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Kim Instrumental v1e Plus · Unwa | config_melband_roformer_inst.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Kim Instrumental v1e · Unwa | config_melband_roformer_inst.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer — Instrumental Metal Preview · Mesk | config_melband_roformer_inst_metal_prev_by_mesk.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |

## Flagged mismatches

| Label | Intent | Backend | Target/Primary | Best result | Flags |
| --- | --- | --- | --- | --- | --- |
| VR v5 — HP Vocals 3 | vocals | two_stem | Vocals | Vocals (+ Instrumental complement) | NAME says vocals but backend is not vocal-focused |
| VR v5 — HP Vocals 4 | vocals | two_stem | Vocals | Vocals (+ Instrumental complement) | NAME says vocals but backend is not vocal-focused |
| MDX23C — D1581 | vocals | two_stem | Vocals | Vocals (+ Instrumental complement) | NAME says vocals but backend is not vocal-focused |

## VR Architecture (detail)

### VR v4 — MGM High-End

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_HIGHEND_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (12.3), vocals (6.9)

### VR v4 — MGM Low-End A

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_LOWEND_A_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.0), vocals (7.0)

### VR v4 — MGM Low-End B

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_LOWEND_B_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.1), vocals (7.5)

### VR v4 — MGM Main

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_MAIN_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (12.4), vocals (6.2)

### VR v5 — SP 2-Band 32 kHz 1

- **Source:** TRvlvr+Politrees
- **Weight:** `10_SP-UVR-2B-32000-1.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.3), vocals (7.5)

### VR v5 — SP 2-Band 32 kHz 2

- **Source:** TRvlvr+Politrees
- **Weight:** `11_SP-UVR-2B-32000-2.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.8), vocals (7.3)

### VR v5 — SP 3-Band 44.1 kHz

- **Source:** TRvlvr+Politrees
- **Weight:** `12_SP-UVR-3B-44100.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.1), vocals (7.5)

### VR v5 — SP 4-Band 44.1 kHz 1

- **Source:** TRvlvr+Politrees
- **Weight:** `13_SP-UVR-4B-44100-1.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.3), vocals (7.8)

### VR v5 — SP 4-Band 44.1 kHz 2

- **Source:** TRvlvr+Politrees
- **Weight:** `14_SP-UVR-4B-44100-2.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.5), vocals (8.0)

### VR v5 — SP Mid 44.1 kHz 1

- **Source:** TRvlvr+Politrees
- **Weight:** `15_SP-UVR-MID-44100-1.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.1), vocals (7.5)

### VR v5 — SP Mid 44.1 kHz 2

- **Source:** TRvlvr+Politrees
- **Weight:** `16_SP-UVR-MID-44100-2.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.3), vocals (7.4)

### VR v5 — HP Wind Instrumental 17

- **Source:** TRvlvr+Politrees
- **Weight:** `17_HP-Wind_Inst-UVR.pth`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `no woodwinds`
- **Instruments:** No Woodwinds, Woodwinds
- **Best result:** no woodwinds (mix minus woodwinds)
- **Save stems UI:** UI: no woodwinds / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: no woodwinds*, woodwinds

### VR v5 — HP 1

- **Source:** TRvlvr+Politrees
- **Weight:** `1_HP-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.7), vocals (7.9)

### VR v5 — HP 2

- **Source:** TRvlvr+Politrees
- **Weight:** `2_HP-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.5), vocals (8.2)

### VR v5 — HP Vocals 3

- **Source:** TRvlvr+Politrees
- **Weight:** `3_HP-Vocal-UVR.pth`
- **Name intent:** vocals
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Instrumental, Vocals
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (8.2), instrumental (14.0)
- **⚠ Flags:** NAME says vocals but backend is not vocal-focused

### VR v5 — HP Vocals 4

- **Source:** TRvlvr+Politrees
- **Weight:** `4_HP-Vocal-UVR.pth`
- **Name intent:** vocals
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Instrumental, Vocals
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (8.3), instrumental (13.6)
- **⚠ Flags:** NAME says vocals but backend is not vocal-focused

### VR v5 — HP Karaoke 5

- **Source:** TRvlvr+Politrees
- **Weight:** `5_HP-Karaoke-UVR.pth`
- **Name intent:** karaoke
- **Backend focus:** karaoke_instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (12.2), vocals (5.2)

### VR v5 — HP Karaoke 6

- **Source:** TRvlvr+Politrees
- **Weight:** `6_HP-Karaoke-UVR.pth`
- **Name intent:** karaoke
- **Backend focus:** karaoke_instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.0), vocals (4.6)

### VR v5 — HP2 7

- **Source:** TRvlvr+Politrees
- **Weight:** `7_HP2-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.5), vocals (8.3)

### VR v5 — HP2 8

- **Source:** TRvlvr+Politrees
- **Weight:** `8_HP2-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.5), vocals (8.2)

### VR v5 — HP2 9

- **Source:** TRvlvr+Politrees
- **Weight:** `9_HP2-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.7), vocals (8.0)

### VR v5 — Karaoke BVE (4 Bands, SN, 44.1 kHz) 1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-BVE-4B_SN-44100-1.pth`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (0.0), instrumental (7.7)

### VR v5 — De-Echo Aggressive · FoxJoy

- **Source:** TRvlvr
- **Weight:** `UVR-De-Echo-Aggressive.pth`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `no echo`
- **Instruments:** Echo, No Echo
- **Best result:** no echo (mix minus echo)
- **Save stems UI:** UI: no echo / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: no echo*, echo

### VR v5 — De-Echo Normal · FoxJoy

- **Source:** TRvlvr
- **Weight:** `UVR-De-Echo-Normal.pth`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `no echo`
- **Instruments:** Echo, No Echo
- **Best result:** no echo (mix minus echo)
- **Save stems UI:** UI: no echo / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: no echo*, echo

### VR v5 — De-Echo/DeReverb · FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-DeEcho-DeReverb.pth`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `no reverb`
- **Instruments:** No Reverb, Reverb
- **Best result:** no reverb (mix minus reverb)
- **Save stems UI:** UI: no reverb / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: no reverb*, reverb

### VR v5 — DeNoise · FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-DeNoise.pth`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `noise`
- **Instruments:** No Noise, Noise
- **Best result:** Noise (isolated noise stem)
- **Save stems UI:** UI: noise / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: noise*, no noise

### VR v5 — DeNoise Lite · FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-DeNoise-Lite.pth`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `noise`
- **Instruments:** No Noise, Noise
- **Best result:** Noise (isolated noise stem)
- **Save stems UI:** UI: noise / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: noise*, no noise

### VR v5 — DeReverb · Aufr33 & Jarredou

- **Source:** Politrees
- **Weight:** `UVR-De-Reverb-aufr33-jarredou.pth`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `dry`
- **Instruments:** Dry, No Dry
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: dry*, no dry

## MDX-Net (detail)

### BandSplit Roformer — Guitar · Kimberley Xlance

- **Source:** mvsepless
- **Weight:** `bs_gtr_xlancer.ckpt`
- **Config:** `bs_gtr_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:guitar
- **Primary stem (backend):** `guitar`
- **Instruments:** guitar, other
- **Target instrument:** `guitar`
- **Best result:** guitar, other
- **Save stems UI:** UI: guitar / other subset
- **Metadata:** bundled_yaml:bs_gtr_xlancer_config.yaml

### BandSplit PolarFormer — 09-07-2026 (4 Stems) · Aname

- **Source:** mvsepless
- **Weight:** `bs_pope_4stem_09072026_aname.ckpt`
- **Config:** `bs_pope_4stem_09072026_aname_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other, drums, bass
- **Best result:** Multi-stem: vocals, other, drums, bass
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_pope_4stem_09072026_aname_config.yaml

### BandSplit PolarFormer — Lazy Bat (4 Stems) · Aname

- **Source:** mvsepless
- **Weight:** `bs_pope_4stem_aname.ckpt`
- **Config:** `bs_pope_4stem_aname_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other, drums, bass
- **Best result:** Multi-stem: vocals, other, drums, bass
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_pope_4stem_aname_config.yaml

### BandSplit PolarFormer — Instrumental/Vocals Duality Lazy Bat · Aname

- **Source:** mvsepless
- **Weight:** `bs_pope_instvoc_aname.ckpt`
- **Config:** `bs_pope_instvoc_aname_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_pope_instvoc_aname_config.yaml

### BandSplit PolarFormer — Karaoke · Lambda001

- **Source:** mvsepless
- **Weight:** `bs_pope_karaoke_974_lambda.ckpt`
- **Config:** `bs_pope_karaoke_974_lambda_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `lead`
- **Instruments:** lead, back_instrum
- **Target instrument:** `lead`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Metadata:** bundled_yaml:bs_pope_karaoke_974_lambda_config.yaml

### BandSplit PolarFormer — Vocals · ZFTurbo

- **Source:** mvsepless
- **Weight:** `bs_pope_vocals_zfturbo.ckpt`
- **Config:** `bs_pope_vocals_zfturbo_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_pope_vocals_zfturbo_config.yaml

### BandSplit Roformer (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `bs_4stem_zfturbo.ckpt`
- **Config:** `bs_4stem_zfturbo_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_4stem_zfturbo_config.yaml

### BandSplit Roformer (4 Stems) · Aname

- **Source:** mvsepless
- **Weight:** `bs_4stem_aname.ckpt`
- **Config:** `bs_4stem_aname_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_4stem_aname_config.yaml

### BandSplit Roformer — Bass Experimental · BeatLoo Labs

- **Source:** mvsepless
- **Weight:** `bs_bass_beatloo_labs.ckpt`
- **Config:** `bs_bass_beatloo_labs_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:bass
- **Primary stem (backend):** `bass`
- **Instruments:** bass, other
- **Target instrument:** `bass`
- **Best result:** Multi-stem: bass, other
- **Metadata:** bundled_yaml:bs_bass_beatloo_labs_config.yaml

### BandSplit Roformer — Bass · Xlance

- **Source:** mvsepless
- **Weight:** `bs_bass_xlancer.ckpt`
- **Config:** `bs_bass_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:bass
- **Primary stem (backend):** `bass`
- **Instruments:** bass, other
- **Target instrument:** `bass`
- **Best result:** Multi-stem: bass, other
- **Metadata:** bundled_yaml:bs_bass_xlancer_config.yaml

### BandSplit Roformer — Bowed Strings · Gilliaaan

- **Source:** mvsepless
- **Weight:** `bs_bowed_str_gilliaaan.ckpt`
- **Config:** `bs_bowed_str_gilliaaan_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:bowed_strings
- **Backend focus:** two_stem
- **Primary stem (backend):** `strings`
- **Instruments:** strings, other
- **Best result:** strings, other
- **Metadata:** bundled_yaml:bs_bowed_str_gilliaaan_config.yaml

### BandSplit Roformer — DeReverb (SDR 22.50) · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_dereverb_2250_anvuew.ckpt`
- **Config:** `bs_dereverb_2250_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:bs_dereverb_2250_anvuew_config.yaml

### BandSplit Roformer — DeReverb 256-8 · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_deverb_256_8_anvuew.ckpt`
- **Config:** `bs_deverb_256_8_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:bs_deverb_256_8_anvuew_config.yaml

### BandSplit Roformer — DeReverb 384-10 · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_deverb_384_10_anvuew.ckpt`
- **Config:** `bs_deverb_384_10_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:bs_deverb_384_10_anvuew_config.yaml

### BandSplit Roformer — DeReverb Room · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_deverb_room_anvuew.ckpt`
- **Config:** `bs_deverb_room_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:bs_deverb_room_anvuew_config.yaml

### BandSplit Roformer — Drums Duality · Gilliaaan

- **Source:** mvsepless
- **Weight:** `bs_drums_gilliaaan.ckpt`
- **Config:** `bs_drums_gilliaaan_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, other
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:bs_drums_gilliaaan_config.yaml

### BandSplit Roformer — Drums Experimental · BeatLoo Labs

- **Source:** mvsepless
- **Weight:** `bs_drums_beatloo_labs.ckpt`
- **Config:** `bs_drums_beatloo_labs_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:drums
- **Primary stem (backend):** `drums`
- **Instruments:** drums, other
- **Target instrument:** `drums`
- **Best result:** Multi-stem: drums, other
- **Metadata:** bundled_yaml:bs_drums_beatloo_labs_config.yaml

### BandSplit Roformer — Drums v1 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_drums_xlancer.ckpt`
- **Config:** `bs_drums_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:drums
- **Primary stem (backend):** `drums`
- **Instruments:** drums, other
- **Target instrument:** `drums`
- **Best result:** Multi-stem: drums, other
- **Metadata:** bundled_yaml:bs_drums_xlancer_config.yaml

### BandSplit Roformer — Drums v2 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_drums2_xlancer.ckpt`
- **Config:** `bs_drums2_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:drums
- **Primary stem (backend):** `drums`
- **Instruments:** drums, other
- **Target instrument:** `drums`
- **Best result:** Multi-stem: drums, other
- **Metadata:** bundled_yaml:bs_drums2_xlancer_config.yaml

### BandSplit Roformer — FNF (Friday Night Funkin) Voices · MrDense67

- **Source:** mvsepless
- **Weight:** `bs_fnf_mrdense67.ckpt`
- **Config:** `bs_fnf_mrdense67_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Voices`
- **Instruments:** Voices, Inst
- **Target instrument:** `Voices`
- **Best result:** Voices (single native output)
- **Metadata:** bundled_yaml:bs_fnf_mrdense67_config.yaml

### BandSplit Roformer — FNF (Friday Night Funkin) Voices v2 · MrDense67

- **Source:** mvsepless
- **Weight:** `bs_fnf2_mrdense67.ckpt`
- **Config:** `bs_fnf2_mrdense67_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Voices`
- **Instruments:** Voices, Inst
- **Target instrument:** `Voices`
- **Best result:** Voices (single native output)
- **Metadata:** bundled_yaml:bs_fnf2_mrdense67_config.yaml

### BandSplit Roformer — Instrumental Beta · neoculture

- **Source:** mvsepless
- **Weight:** `bs_neo_inst_beta.ckpt`
- **Config:** `bs_neo_inst_beta_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_neo_inst_beta_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Instrumental EXP Value Residual · Unwa

- **Source:** mvsepless
- **Weight:** `bs_inst_exp_vlp_unwa.ckpt`
- **Config:** `bs_inst_exp_vlp_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_inst_exp_vlp_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Instrumental FNO · Unwa

- **Source:** mvsepless
- **Weight:** `bs_inst_fno_unwa.ckpt`
- **Config:** `bs_inst_fno_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_inst_fno_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Instrumental HyperACE · Unwa

- **Source:** mvsepless
- **Weight:** `bs_inst_hyperace_unwa.ckpt`
- **Config:** `bs_inst_hyperace_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** single_target:instrument
- **Primary stem (backend):** `instrument`
- **Instruments:** vocals, instrument
- **Target instrument:** `instrument`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:bs_inst_hyperace_unwa_config.yaml

### BandSplit Roformer — Instrumental HyperACE v2 · Unwa

- **Source:** mvsepless
- **Weight:** `bs_inst_hyperace2_unwa.ckpt`
- **Config:** `bs_inst_hyperace2_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** single_target:instrument
- **Primary stem (backend):** `instrument`
- **Instruments:** vocals, instrument
- **Target instrument:** `instrument`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:bs_inst_hyperace2_unwa_config.yaml

### BandSplit Roformer — Instrumental Large v2 · Unwa

- **Source:** mvsepless
- **Weight:** `bs_inst_large2_unwa.ckpt`
- **Config:** `bs_inst_large2_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** single_target:instrument
- **Primary stem (backend):** `instrument`
- **Instruments:** vocals, instrument
- **Target instrument:** `instrument`
- **Best result:** instrument (single native output)
- **Metadata:** bundled_yaml:bs_inst_large2_unwa_config.yaml

### BandSplit Roformer — Instrumental Resurrection · Gabox

- **Source:** mvsepless
- **Weight:** `bs_resurrection_inst_gabox.ckpt`
- **Config:** `bs_resurrection_inst_gabox_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_resurrection_inst_gabox_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Instrumental Resurrection · Unwa

- **Source:** mvsepless
- **Weight:** `bs_resurrection_inst_unwa.ckpt`
- **Config:** `bs_resurrection_inst_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_resurrection_inst_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Karaoke Inverted · GaboxR67

- **Source:** mvsepless
- **Weight:** `bs_karaoke_inv_gabox.ckpt`
- **Config:** `bs_karaoke_inv_gabox_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_instrumental_primary
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_karaoke_inv_gabox_config.yaml

### BandSplit Roformer — Karaoke · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_karaoke_anvuew.ckpt`
- **Config:** `bs_karaoke_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_karaoke_anvuew_config.yaml

### BandSplit Roformer — Karaoke · Becruily & Frazer

- **Source:** mvsepless
- **Weight:** `bs_karaoke_becruily.ckpt`
- **Config:** `bs_karaoke_becruily_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_karaoke_becruily_config.yaml

### BandSplit Roformer — Karaoke · GaboxR67

- **Source:** mvsepless
- **Weight:** `bs_karaoke_gabox.ckpt`
- **Config:** `bs_karaoke_gabox_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_karaoke_gabox_config.yaml

### BandSplit Roformer — Karaoke · GiantAILAB

- **Source:** mvsepless
- **Weight:** `bs_karaoke_3stem_giantailab.ckpt`
- **Config:** `bs_karaoke_3stem_giantailab_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, backing_vocal, instrumental
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_karaoke_3stem_giantailab_config.yaml

### BandSplit Roformer — Keys · Xlance

- **Source:** mvsepless
- **Weight:** `bs_keys_xlancer.ckpt`
- **Config:** `bs_keys_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:keys
- **Backend focus:** single_target:keys
- **Primary stem (backend):** `keys`
- **Instruments:** keys, other
- **Target instrument:** `keys`
- **Best result:** keys (single native output)
- **Metadata:** bundled_yaml:bs_keys_xlancer_config.yaml

### BandSplit Roformer — Leap Instrumental · Unwa

- **Source:** mvsepless
- **Weight:** `bs_leap_inst_unwa.ckpt`
- **Config:** `bs_leap_inst_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_leap_inst_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Leap Vocals · Unwa

- **Source:** mvsepless
- **Weight:** `bs_leap_voc_unwa.ckpt`
- **Config:** `bs_leap_voc_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_leap_voc_unwa_config.yaml

### BandSplit Roformer — Leap XE (90 bands) Instrumental · Unwa

- **Source:** mvsepless
- **Weight:** `bs_leap_xe_inst_unwa.ckpt`
- **Config:** `bs_leap_xe_inst_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_leap_xe_inst_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Leap XE (90 bands) Vocals · Unwa

- **Source:** mvsepless
- **Weight:** `bs_leap_xe_voc_unwa.ckpt`
- **Config:** `bs_leap_xe_voc_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_leap_xe_voc_unwa_config.yaml

### BandSplit Roformer — Logic (6 Stems) · Chantrail

- **Source:** mvsepless
- **Weight:** `bs_logic_6stem.ckpt`
- **Config:** `bs_logic_6stem_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `bass`
- **Instruments:** bass, drums, other, vocals, guitar, piano
- **Best result:** Multi-stem: bass, drums, other, vocals, guitar, piano
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_logic_6stem_config.yaml

### BandSplit Roformer — Mag (3179) · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_mag_3179_anvuew.ckpt`
- **Config:** `bs_mag_3179_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_mag_3179_anvuew_config.yaml

### BandSplit Roformer — Mag · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_mag_anvuew.ckpt`
- **Config:** `bs_mag_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_mag_anvuew_config.yaml

### BandSplit Roformer — Male/Female (ep 146) · Sucial

- **Source:** mvsepless
- **Weight:** `bs_male_female_146_sucial.ckpt`
- **Config:** `bs_male_female_146_sucial_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_two_stem
- **Primary stem (backend):** `male`
- **Instruments:** male, female
- **Best result:** male, female
- **Save stems UI:** UI: male / female subset
- **Metadata:** bundled_yaml:bs_male_female_146_sucial_config.yaml

### BandSplit Roformer — Male/Female (ep 267) · Sucial

- **Source:** mvsepless
- **Weight:** `bs_male_female_267_sucial.ckpt`
- **Config:** `bs_male_female_267_sucial_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_two_stem
- **Primary stem (backend):** `male`
- **Instruments:** male, female
- **Best result:** male, female
- **Save stems UI:** UI: male / female subset
- **Metadata:** bundled_yaml:bs_male_female_267_sucial_config.yaml

### BandSplit Roformer — Mega Full (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_full_mvsep.ckpt`
- **Config:** `bs_mega_53stem_full_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `accordion`
- **Instruments:** accordion, acoustic-guitar, back-vocal, banjo, bass, bassoon, bells, bowed_strings, brass, cello, clarinet, congas, digital-piano, dobro, double-bass, drums, electric-guitar, flute, french-horn, glockenspiel, guitar, harmonica, harp, harpsichord, hh, keys, kick, lead-vocal, mandolin, marimba, oboe, organ, percussion, piano, saxophone, sitar, snare, strings, synth, tambourine, timpani, toms, triangle, trombone, trumpet, tuba, ukulele, viola, violin, vocal, wind, wind-chimes, woodwind
- **Best result:** Multi-stem: accordion, acoustic-guitar, back-vocal, banjo, bass, bassoon, bells, bowed_strings, brass, cello, clarinet, congas, digital-piano, dobro, double-bass, drums, electric-guitar, flute, french-horn, glockenspiel, guitar, harmonica, harp, harpsichord, hh, keys, kick, lead-vocal, mandolin, marimba, oboe, organ, percussion, piano, saxophone, sitar, snare, strings, synth, tambourine, timpani, toms, triangle, trombone, trumpet, tuba, ukulele, viola, violin, vocal, wind, wind-chimes, woodwind
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_mega_53stem_full_mvsep_config.yaml

### BandSplit Roformer — Mega Accordion Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_accordion_mvsep.ckpt`
- **Config:** `bs_mega_53stem_accordion_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:accordion
- **Backend focus:** single_target:accordion
- **Primary stem (backend):** `accordion`
- **Instruments:** accordion, other
- **Target instrument:** `accordion`
- **Best result:** accordion (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_accordion_mvsep_config.yaml

### BandSplit Roformer — Mega Acoustic Guitar Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_acoustic-guitar_mvsep.ckpt`
- **Config:** `bs_mega_53stem_acoustic-guitar_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:acoustic_guitar
- **Backend focus:** single_target:acoustic-guitar
- **Primary stem (backend):** `acoustic-guitar`
- **Instruments:** acoustic-guitar, other
- **Target instrument:** `acoustic-guitar`
- **Best result:** acoustic-guitar (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_acoustic-guitar_mvsep_config.yaml

### BandSplit Roformer — Mega Backing Vocals Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_back-vocal_mvsep.ckpt`
- **Config:** `bs_mega_53stem_back-vocal_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** specialty_stem
- **Backend focus:** single_target:back-vocal
- **Primary stem (backend):** `back-vocal`
- **Instruments:** back-vocal, other
- **Target instrument:** `back-vocal`
- **Best result:** back-vocal, other
- **Save stems UI:** UI: back-vocal / other subset
- **Metadata:** bundled_yaml:bs_mega_53stem_back-vocal_mvsep_config.yaml
- **Note:** Name intent corrected from metadata (specialty_stem)

### BandSplit Roformer — Mega Banjo Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_banjo_mvsep.ckpt`
- **Config:** `bs_mega_53stem_banjo_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:banjo
- **Backend focus:** single_target:banjo
- **Primary stem (backend):** `banjo`
- **Instruments:** banjo, other
- **Target instrument:** `banjo`
- **Best result:** banjo (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_banjo_mvsep_config.yaml

### BandSplit Roformer — Mega Bass Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_bass_mvsep.ckpt`
- **Config:** `bs_mega_53stem_bass_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:bass
- **Primary stem (backend):** `bass`
- **Instruments:** bass, other
- **Target instrument:** `bass`
- **Best result:** Multi-stem: bass, other
- **Metadata:** bundled_yaml:bs_mega_53stem_bass_mvsep_config.yaml

### BandSplit Roformer — Mega Bassoon Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_bassoon_mvsep.ckpt`
- **Config:** `bs_mega_53stem_bassoon_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:bassoon
- **Primary stem (backend):** `bassoon`
- **Instruments:** bassoon, other
- **Target instrument:** `bassoon`
- **Best result:** Multi-stem: bassoon, other
- **Metadata:** bundled_yaml:bs_mega_53stem_bassoon_mvsep_config.yaml

### BandSplit Roformer — Mega Bells Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_bells_mvsep.ckpt`
- **Config:** `bs_mega_53stem_bells_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:bells
- **Backend focus:** single_target:bells
- **Primary stem (backend):** `bells`
- **Instruments:** bells, other
- **Target instrument:** `bells`
- **Best result:** bells (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_bells_mvsep_config.yaml

### BandSplit Roformer — Mega Bowed Strings Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_bowed_strings_mvsep.ckpt`
- **Config:** `bs_mega_53stem_bowed_strings_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:bowed_strings
- **Backend focus:** single_target:bowed_strings
- **Primary stem (backend):** `bowed_strings`
- **Instruments:** bowed_strings, other
- **Target instrument:** `bowed_strings`
- **Best result:** bowed_strings (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_bowed_strings_mvsep_config.yaml

### BandSplit Roformer — Mega Brass Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_brass_mvsep.ckpt`
- **Config:** `bs_mega_53stem_brass_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:brass
- **Backend focus:** single_target:brass
- **Primary stem (backend):** `brass`
- **Instruments:** brass, other
- **Target instrument:** `brass`
- **Best result:** brass (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_brass_mvsep_config.yaml

### BandSplit Roformer — Mega Cello Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_cello_mvsep.ckpt`
- **Config:** `bs_mega_53stem_cello_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:cello
- **Backend focus:** single_target:cello
- **Primary stem (backend):** `cello`
- **Instruments:** cello, other
- **Target instrument:** `cello`
- **Best result:** cello (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_cello_mvsep_config.yaml

### BandSplit Roformer — Mega Clarinet Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_clarinet_mvsep.ckpt`
- **Config:** `bs_mega_53stem_clarinet_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:clarinet
- **Backend focus:** single_target:clarinet
- **Primary stem (backend):** `clarinet`
- **Instruments:** clarinet, other
- **Target instrument:** `clarinet`
- **Best result:** clarinet (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_clarinet_mvsep_config.yaml

### BandSplit Roformer — Mega Congas Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_congas_mvsep.ckpt`
- **Config:** `bs_mega_53stem_congas_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:congas
- **Backend focus:** single_target:congas
- **Primary stem (backend):** `congas`
- **Instruments:** congas, other
- **Target instrument:** `congas`
- **Best result:** congas (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_congas_mvsep_config.yaml

### BandSplit Roformer — Mega Digital Piano Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_digital-piano_mvsep.ckpt`
- **Config:** `bs_mega_53stem_digital-piano_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:digital_piano
- **Backend focus:** single_target:digital-piano
- **Primary stem (backend):** `digital-piano`
- **Instruments:** digital-piano, other
- **Target instrument:** `digital-piano`
- **Best result:** digital-piano (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_digital-piano_mvsep_config.yaml

### BandSplit Roformer — Mega Dobro Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_dobro_mvsep.ckpt`
- **Config:** `bs_mega_53stem_dobro_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:dobro
- **Backend focus:** single_target:dobro
- **Primary stem (backend):** `dobro`
- **Instruments:** dobro, other
- **Target instrument:** `dobro`
- **Best result:** dobro (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_dobro_mvsep_config.yaml

### BandSplit Roformer — Mega Double Bass Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_double-bass_mvsep.ckpt`
- **Config:** `bs_mega_53stem_double-bass_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:double-bass
- **Primary stem (backend):** `double-bass`
- **Instruments:** double-bass, other
- **Target instrument:** `double-bass`
- **Best result:** Multi-stem: double-bass, other
- **Metadata:** bundled_yaml:bs_mega_53stem_double-bass_mvsep_config.yaml

### BandSplit Roformer — Mega Drums Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_drums_mvsep.ckpt`
- **Config:** `bs_mega_53stem_drums_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:drums
- **Primary stem (backend):** `drums`
- **Instruments:** drums, other
- **Target instrument:** `drums`
- **Best result:** Multi-stem: drums, other
- **Metadata:** bundled_yaml:bs_mega_53stem_drums_mvsep_config.yaml

### BandSplit Roformer — Mega Electric Guitar Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_electric-guitar_mvsep.ckpt`
- **Config:** `bs_mega_53stem_electric-guitar_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:electric_guitar
- **Backend focus:** single_target:electric-guitar
- **Primary stem (backend):** `electric-guitar`
- **Instruments:** electric-guitar, other
- **Target instrument:** `electric-guitar`
- **Best result:** electric-guitar (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_electric-guitar_mvsep_config.yaml

### BandSplit Roformer — Mega Flute Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_flute_mvsep.ckpt`
- **Config:** `bs_mega_53stem_flute_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:flute
- **Backend focus:** single_target:flute
- **Primary stem (backend):** `flute`
- **Instruments:** flute, other
- **Target instrument:** `flute`
- **Best result:** flute (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_flute_mvsep_config.yaml

### BandSplit Roformer — Mega French Horn Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_french-horn_mvsep.ckpt`
- **Config:** `bs_mega_53stem_french-horn_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:french_horn
- **Backend focus:** single_target:french-horn
- **Primary stem (backend):** `french-horn`
- **Instruments:** french-horn, other
- **Target instrument:** `french-horn`
- **Best result:** french-horn (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_french-horn_mvsep_config.yaml

### BandSplit Roformer — Mega Glockenspiel Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_glockenspiel_mvsep.ckpt`
- **Config:** `bs_mega_53stem_glockenspiel_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:glockenspiel
- **Backend focus:** single_target:glockenspiel
- **Primary stem (backend):** `glockenspiel`
- **Instruments:** glockenspiel, other
- **Target instrument:** `glockenspiel`
- **Best result:** glockenspiel (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_glockenspiel_mvsep_config.yaml

### BandSplit Roformer — Mega Guitar Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_guitar_mvsep.ckpt`
- **Config:** `bs_mega_53stem_guitar_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:guitar
- **Backend focus:** specialty_target:guitar
- **Primary stem (backend):** `guitar`
- **Instruments:** guitar, other
- **Target instrument:** `guitar`
- **Best result:** guitar (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_guitar_mvsep_config.yaml

### BandSplit Roformer — Mega Harmonica Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_harmonica_mvsep.ckpt`
- **Config:** `bs_mega_53stem_harmonica_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:harmonica
- **Backend focus:** single_target:harmonica
- **Primary stem (backend):** `harmonica`
- **Instruments:** harmonica, other
- **Target instrument:** `harmonica`
- **Best result:** harmonica (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_harmonica_mvsep_config.yaml

### BandSplit Roformer — Mega Harp Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_harp_mvsep.ckpt`
- **Config:** `bs_mega_53stem_harp_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:harp
- **Backend focus:** single_target:harp
- **Primary stem (backend):** `harp`
- **Instruments:** harp, other
- **Target instrument:** `harp`
- **Best result:** harp (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_harp_mvsep_config.yaml

### BandSplit Roformer — Mega Harpsichord Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_harpsichord_mvsep.ckpt`
- **Config:** `bs_mega_53stem_harpsichord_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:harpsichord
- **Backend focus:** single_target:harpsichord
- **Primary stem (backend):** `harpsichord`
- **Instruments:** harpsichord, other
- **Target instrument:** `harpsichord`
- **Best result:** harpsichord (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_harpsichord_mvsep_config.yaml

### BandSplit Roformer — Mega Hi-Hat Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_hh_mvsep.ckpt`
- **Config:** `bs_mega_53stem_hh_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:hh
- **Backend focus:** single_target:hh
- **Primary stem (backend):** `hh`
- **Instruments:** hh, other
- **Target instrument:** `hh`
- **Best result:** hh (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_hh_mvsep_config.yaml

### BandSplit Roformer — Mega Keys Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_keys_mvsep.ckpt`
- **Config:** `bs_mega_53stem_keys_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:keys
- **Backend focus:** single_target:keys
- **Primary stem (backend):** `keys`
- **Instruments:** keys, other
- **Target instrument:** `keys`
- **Best result:** keys (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_keys_mvsep_config.yaml

### BandSplit Roformer — Mega Kick Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_kick_mvsep.ckpt`
- **Config:** `bs_mega_53stem_kick_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:kick
- **Backend focus:** single_target:kick
- **Primary stem (backend):** `kick`
- **Instruments:** kick, other
- **Target instrument:** `kick`
- **Best result:** kick (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_kick_mvsep_config.yaml

### BandSplit Roformer — Mega Lead Vocals Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_lead-vocal_mvsep.ckpt`
- **Config:** `bs_mega_53stem_lead-vocal_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `lead-vocal`
- **Instruments:** lead-vocal, other
- **Target instrument:** `lead-vocal`
- **Best result:** lead-vocal (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_lead-vocal_mvsep_config.yaml

### BandSplit Roformer — Mega Mandolin Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_mandolin_mvsep.ckpt`
- **Config:** `bs_mega_53stem_mandolin_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:mandolin
- **Backend focus:** single_target:mandolin
- **Primary stem (backend):** `mandolin`
- **Instruments:** mandolin, other
- **Target instrument:** `mandolin`
- **Best result:** mandolin (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_mandolin_mvsep_config.yaml

### BandSplit Roformer — Mega Marimba Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_marimba_mvsep.ckpt`
- **Config:** `bs_mega_53stem_marimba_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:marimba
- **Backend focus:** single_target:marimba
- **Primary stem (backend):** `marimba`
- **Instruments:** marimba, other
- **Target instrument:** `marimba`
- **Best result:** marimba (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_marimba_mvsep_config.yaml

### BandSplit Roformer — Mega Oboe Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_oboe_mvsep.ckpt`
- **Config:** `bs_mega_53stem_oboe_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:oboe
- **Backend focus:** single_target:oboe
- **Primary stem (backend):** `oboe`
- **Instruments:** oboe, other
- **Target instrument:** `oboe`
- **Best result:** oboe (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_oboe_mvsep_config.yaml

### BandSplit Roformer — Mega Organ Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_organ_mvsep.ckpt`
- **Config:** `bs_mega_53stem_organ_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:organ
- **Backend focus:** single_target:organ
- **Primary stem (backend):** `organ`
- **Instruments:** organ, other
- **Target instrument:** `organ`
- **Best result:** organ (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_organ_mvsep_config.yaml

### BandSplit Roformer — Mega Percussion Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_percussion_mvsep.ckpt`
- **Config:** `bs_mega_53stem_percussion_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:percussion
- **Backend focus:** single_target:percussion
- **Primary stem (backend):** `percussion`
- **Instruments:** percussion, other
- **Target instrument:** `percussion`
- **Best result:** percussion (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_percussion_mvsep_config.yaml

### BandSplit Roformer — Mega Piano Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_piano_mvsep.ckpt`
- **Config:** `bs_mega_53stem_piano_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:piano
- **Backend focus:** single_target:piano
- **Primary stem (backend):** `piano`
- **Instruments:** piano, other
- **Target instrument:** `piano`
- **Best result:** piano (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_piano_mvsep_config.yaml

### BandSplit Roformer — Mega Saxophone Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_saxophone_mvsep.ckpt`
- **Config:** `bs_mega_53stem_saxophone_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:saxophone
- **Backend focus:** single_target:saxophone
- **Primary stem (backend):** `saxophone`
- **Instruments:** saxophone, other
- **Target instrument:** `saxophone`
- **Best result:** saxophone (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_saxophone_mvsep_config.yaml

### BandSplit Roformer — Mega Sitar Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_sitar_mvsep.ckpt`
- **Config:** `bs_mega_53stem_sitar_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:sitar
- **Backend focus:** single_target:sitar
- **Primary stem (backend):** `sitar`
- **Instruments:** sitar, other
- **Target instrument:** `sitar`
- **Best result:** sitar (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_sitar_mvsep_config.yaml

### BandSplit Roformer — Mega Snare Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_snare_mvsep.ckpt`
- **Config:** `bs_mega_53stem_snare_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:snare
- **Backend focus:** single_target:snare
- **Primary stem (backend):** `snare`
- **Instruments:** snare, other
- **Target instrument:** `snare`
- **Best result:** snare (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_snare_mvsep_config.yaml

### BandSplit Roformer — Mega Strings Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_strings_mvsep.ckpt`
- **Config:** `bs_mega_53stem_strings_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:strings
- **Backend focus:** single_target:strings
- **Primary stem (backend):** `strings`
- **Instruments:** strings, other
- **Target instrument:** `strings`
- **Best result:** strings (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_strings_mvsep_config.yaml

### BandSplit Roformer — Mega Synth Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_synth_mvsep.ckpt`
- **Config:** `bs_mega_53stem_synth_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:synth
- **Backend focus:** single_target:synth
- **Primary stem (backend):** `synth`
- **Instruments:** synth, other
- **Target instrument:** `synth`
- **Best result:** synth (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_synth_mvsep_config.yaml

### BandSplit Roformer — Mega Tambourine Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_tambourine_mvsep.ckpt`
- **Config:** `bs_mega_53stem_tambourine_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:tambourine
- **Backend focus:** single_target:tambourine
- **Primary stem (backend):** `tambourine`
- **Instruments:** tambourine, other
- **Target instrument:** `tambourine`
- **Best result:** tambourine (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_tambourine_mvsep_config.yaml

### BandSplit Roformer — Mega Timpani Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_timpani_mvsep.ckpt`
- **Config:** `bs_mega_53stem_timpani_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:timpani
- **Backend focus:** single_target:timpani
- **Primary stem (backend):** `timpani`
- **Instruments:** timpani, other
- **Target instrument:** `timpani`
- **Best result:** timpani (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_timpani_mvsep_config.yaml

### BandSplit Roformer — Mega Toms Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_toms_mvsep.ckpt`
- **Config:** `bs_mega_53stem_toms_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:toms
- **Backend focus:** single_target:toms
- **Primary stem (backend):** `toms`
- **Instruments:** toms, other
- **Target instrument:** `toms`
- **Best result:** toms (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_toms_mvsep_config.yaml

### BandSplit Roformer — Mega Triangle Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_triangle_mvsep.ckpt`
- **Config:** `bs_mega_53stem_triangle_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:triangle
- **Backend focus:** single_target:triangle
- **Primary stem (backend):** `triangle`
- **Instruments:** triangle, other
- **Target instrument:** `triangle`
- **Best result:** triangle (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_triangle_mvsep_config.yaml

### BandSplit Roformer — Mega Trombone Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_trombone_mvsep.ckpt`
- **Config:** `bs_mega_53stem_trombone_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:trombone
- **Backend focus:** single_target:trombone
- **Primary stem (backend):** `trombone`
- **Instruments:** trombone, other
- **Target instrument:** `trombone`
- **Best result:** trombone (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_trombone_mvsep_config.yaml

### BandSplit Roformer — Mega Trumpet Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_trumpet_mvsep.ckpt`
- **Config:** `bs_mega_53stem_trumpet_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:trumpet
- **Backend focus:** single_target:trumpet
- **Primary stem (backend):** `trumpet`
- **Instruments:** trumpet, other
- **Target instrument:** `trumpet`
- **Best result:** trumpet (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_trumpet_mvsep_config.yaml

### BandSplit Roformer — Mega Tuba Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_tuba_mvsep.ckpt`
- **Config:** `bs_mega_53stem_tuba_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:tuba
- **Backend focus:** single_target:tuba
- **Primary stem (backend):** `tuba`
- **Instruments:** tuba, other
- **Target instrument:** `tuba`
- **Best result:** tuba (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_tuba_mvsep_config.yaml

### BandSplit Roformer — Mega Ukulele Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_ukulele_mvsep.ckpt`
- **Config:** `bs_mega_53stem_ukulele_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:ukulele
- **Backend focus:** single_target:ukulele
- **Primary stem (backend):** `ukulele`
- **Instruments:** ukulele, other
- **Target instrument:** `ukulele`
- **Best result:** ukulele (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_ukulele_mvsep_config.yaml

### BandSplit Roformer — Mega Viola Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_viola_mvsep.ckpt`
- **Config:** `bs_mega_53stem_viola_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:viola
- **Backend focus:** single_target:viola
- **Primary stem (backend):** `viola`
- **Instruments:** viola, other
- **Target instrument:** `viola`
- **Best result:** viola (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_viola_mvsep_config.yaml

### BandSplit Roformer — Mega Violin Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_violin_mvsep.ckpt`
- **Config:** `bs_mega_53stem_violin_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:violin
- **Backend focus:** single_target:violin
- **Primary stem (backend):** `violin`
- **Instruments:** violin, other
- **Target instrument:** `violin`
- **Best result:** violin (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_violin_mvsep_config.yaml

### BandSplit Roformer — Mega Vocals Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_vocal_mvsep.ckpt`
- **Config:** `bs_mega_53stem_vocal_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocal`
- **Instruments:** vocal, other
- **Target instrument:** `vocal`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_mega_53stem_vocal_mvsep_config.yaml

### BandSplit Roformer — Mega Wind Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_wind_mvsep.ckpt`
- **Config:** `bs_mega_53stem_wind_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:wind
- **Backend focus:** single_target:wind
- **Primary stem (backend):** `wind`
- **Instruments:** wind, other
- **Target instrument:** `wind`
- **Best result:** wind (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_wind_mvsep_config.yaml

### BandSplit Roformer — Mega Wind Chimes Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_wind-chimes_mvsep.ckpt`
- **Config:** `bs_mega_53stem_wind-chimes_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:wind_chimes
- **Backend focus:** single_target:wind-chimes
- **Primary stem (backend):** `wind-chimes`
- **Instruments:** wind-chimes, other
- **Target instrument:** `wind-chimes`
- **Best result:** wind-chimes (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_wind-chimes_mvsep_config.yaml

### BandSplit Roformer — Mega Woodwind Only (53 Stems) · MVSep

- **Source:** mvsepless
- **Weight:** `bs_mega_53stem_woodwind_mvsep.ckpt`
- **Config:** `bs_mega_53stem_woodwind_mvsep_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:woodwind
- **Backend focus:** single_target:woodwind
- **Primary stem (backend):** `woodwind`
- **Instruments:** woodwind, other
- **Target instrument:** `woodwind`
- **Best result:** woodwind (single native output)
- **Metadata:** bundled_yaml:bs_mega_53stem_woodwind_mvsep_config.yaml

### BandSplit Roformer — Mid-Side v1 · Gilliaaan

- **Source:** mvsepless
- **Weight:** `bs_mid_side1_gilliaaan.ckpt`
- **Config:** `bs_mid_side1_gilliaaan_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** spatial
- **Backend focus:** single_target:center
- **Primary stem (backend):** `center`
- **Instruments:** center, wide
- **Target instrument:** `center`
- **Best result:** center (single native output)
- **Metadata:** bundled_yaml:bs_mid_side1_gilliaaan_config.yaml

### BandSplit Roformer — Mid-Side v2 · Gilliaaan

- **Source:** mvsepless
- **Weight:** `bs_mid_side2_gilliaaan.ckpt`
- **Config:** `bs_mid_side2_gilliaaan_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** spatial
- **Backend focus:** single_target:center
- **Primary stem (backend):** `center`
- **Instruments:** center, wide
- **Target instrument:** `center`
- **Best result:** center (single native output)
- **Metadata:** bundled_yaml:bs_mid_side2_gilliaaan_config.yaml

### BandSplit Roformer — Orchestra v1 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_orch_xlancer.ckpt`
- **Config:** `bs_orch_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:orch
- **Backend focus:** single_target:orch
- **Primary stem (backend):** `orch`
- **Instruments:** orch, other
- **Target instrument:** `orch`
- **Best result:** orch (single native output)
- **Metadata:** bundled_yaml:bs_orch_xlancer_config.yaml

### BandSplit Roformer — Orchestra v2 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_orch2_xlancer.ckpt`
- **Config:** `bs_orch_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:orch
- **Backend focus:** single_target:orch
- **Primary stem (backend):** `orch`
- **Instruments:** orch, other
- **Target instrument:** `orch`
- **Best result:** orch (single native output)
- **Metadata:** bundled_yaml:bs_orch_xlancer_config.yaml

### BandSplit Roformer — Other · ViperX

- **Source:** mvsepless
- **Weight:** `bs_other_viperx.ckpt`
- **Config:** `bs_other_viperx_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_other_viperx_config.yaml

### BandSplit Roformer — Percussion v1 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_perc_xlancer.ckpt`
- **Config:** `bs_perc_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:percussion
- **Backend focus:** single_target:percussion
- **Primary stem (backend):** `percussion`
- **Instruments:** percussion, other
- **Target instrument:** `percussion`
- **Best result:** percussion (single native output)
- **Metadata:** bundled_yaml:bs_perc_xlancer_config.yaml

### BandSplit Roformer — Percussion v2 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_perc2_xlancer.ckpt`
- **Config:** `bs_perc2_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:percussion
- **Backend focus:** single_target:percussion
- **Primary stem (backend):** `percussion`
- **Instruments:** percussion, other
- **Target instrument:** `percussion`
- **Best result:** percussion (single native output)
- **Metadata:** bundled_yaml:bs_perc2_xlancer_config.yaml

### BandSplit Roformer — Resurrection v2 (Quality Test) · Unwa

- **Source:** mvsepless
- **Weight:** `bs_resurrection2_quality_test_unwa.ckpt`
- **Config:** `bs_resurrection2_quality_test_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_resurrection2_quality_test_unwa_config.yaml

### BandSplit Roformer — SW

- **Source:** mvsepless
- **Weight:** `bs_6stem.ckpt`
- **Config:** `bs_6stem_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `bass`
- **Instruments:** bass, drums, other, vocals, guitar, piano
- **Best result:** Multi-stem: bass, drums, other, vocals, guitar, piano
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_6stem_config.yaml

### BandSplit Roformer — SW Fixed · Jarredou

- **Source:** mvsepless
- **Weight:** `bs_6stem_fixed.ckpt`
- **Config:** `bs_6stem_fixed_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `bass`
- **Instruments:** bass, drums, other, vocals, guitar, piano
- **Best result:** Multi-stem: bass, drums, other, vocals, guitar, piano
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bs_6stem_fixed_config.yaml

### BandSplit Roformer — SpeechSep · AliceN

- **Source:** mvsepless
- **Weight:** `bs_speech_alicen.ckpt`
- **Config:** `bs_speech_alicen_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_speech_alicen_config.yaml

### BandSplit Roformer — Synth v1 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_syn_xlancer.ckpt`
- **Config:** `bs_syn_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:synth
- **Backend focus:** single_target:synth
- **Primary stem (backend):** `synth`
- **Instruments:** synth, other
- **Target instrument:** `synth`
- **Best result:** synth (single native output)
- **Metadata:** bundled_yaml:bs_syn_xlancer_config.yaml

### BandSplit Roformer — Synth v2 · Xlance

- **Source:** mvsepless
- **Weight:** `bs_syn2_xlancer.ckpt`
- **Config:** `bs_syn2_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrument_target:synth
- **Backend focus:** single_target:synth
- **Primary stem (backend):** `synth`
- **Instruments:** synth, other
- **Target instrument:** `synth`
- **Best result:** synth (single native output)
- **Metadata:** bundled_yaml:bs_syn2_xlancer_config.yaml

### BandSplit Roformer — Vocals (SDR 12.96) · ViperX

- **Source:** mvsepless
- **Weight:** `bs_vocals_1296_viperx.ckpt`
- **Config:** `bs_vocals_1296_viperx_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_vocals_1296_viperx_config.yaml

### BandSplit Roformer — Vocals (SDR 12.97) · ViperX

- **Source:** mvsepless
- **Weight:** `bs_vocals_1297_viperx.ckpt`
- **Config:** `bs_vocals_1297_viperx_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_vocals_1297_viperx_config.yaml

### BandSplit Roformer — Vocals Fine-Tuned v1 · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_vocalsft1_anvuew.ckpt`
- **Config:** `bs_vocalsft1_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_vocalsft1_anvuew_config.yaml

### BandSplit Roformer — Vocals HyperACE v2 · Unwa

- **Source:** mvsepless
- **Weight:** `bs_voc_hyperace2_unwa.ckpt`
- **Config:** `bs_voc_hyperace2_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_voc_hyperace2_unwa_config.yaml

### BandSplit Roformer — Vocals Large v1 · Unwa

- **Source:** mvsepless
- **Weight:** `bs_vocals_large1_unwa.ckpt`
- **Config:** `bs_vocals_large1_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_vocals_large1_unwa_config.yaml

### BandSplit Roformer — Vocals Resurrection · Unwa

- **Source:** mvsepless
- **Weight:** `bs_resurrection_unwa.ckpt`
- **Config:** `bs_resurrection_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_resurrection_unwa_config.yaml

### BandSplit Roformer — Vocals Revive v1 · Unwa

- **Source:** mvsepless
- **Weight:** `bs_revive1_unwa.ckpt`
- **Config:** `bs_revive1_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_revive1_unwa_config.yaml

### BandSplit Roformer — Vocals Revive v2 · Unwa

- **Source:** mvsepless
- **Weight:** `bs_revive2_unwa.ckpt`
- **Config:** `bs_revive2_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_revive2_unwa_config.yaml

### BandSplit Roformer — Vocals Revive v3e · Unwa

- **Source:** mvsepless
- **Weight:** `bs_revive3e_unwa.ckpt`
- **Config:** `bs_revive3e_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_revive3e_unwa_config.yaml

### BandSplit Roformer — Vocals · Anvuew

- **Source:** mvsepless
- **Weight:** `bs_vocals_anvuew.ckpt`
- **Config:** `bs_vocals_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_vocals_anvuew_config.yaml

### BandSplit Roformer — Vocals · GaboxR67

- **Source:** mvsepless
- **Weight:** `bs_voctest_gabox.ckpt`
- **Config:** `bs_voctest_gabox_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_voctest_gabox_config.yaml

### BandSplit Roformer — Vocals v1 · Aname

- **Source:** mvsepless
- **Weight:** `bs_vocals1_aname.ckpt`
- **Config:** `bs_vocals_anvuew_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_vocals_anvuew_config.yaml

### BandSplit Roformer — Vocals v2 · Aname

- **Source:** mvsepless
- **Weight:** `bs_vocals2_aname.ckpt`
- **Config:** `bs_vocals2_aname_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:bs_vocals2_aname_config.yaml

### BandSplit Roformer — Vocals · Xlance

- **Source:** mvsepless
- **Weight:** `bs_vox_xlancer.ckpt`
- **Config:** `bs_vox_xlancer_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vox`
- **Instruments:** vox, other
- **Target instrument:** `vox`
- **Best result:** vox (single native output)
- **Metadata:** bundled_yaml:bs_vox_xlancer_config.yaml

### BandSplit Roformer — Siamese Vocals · Unwa

- **Source:** mvsepless
- **Weight:** `bs_siamese_vocals_unwa.ckpt`
- **Config:** `bs_siamese_vocals_unwa_config.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:bs_siamese_vocals_unwa_config.yaml

## Bandit (detail)

### Bandit — Last Checkpoint · ZFTurbo

- **Source:** mvsepless
- **Weight:** `bandit_last.ckpt`
- **Config:** `bandit_last_config.yaml`
- **Architecture:** Bandit
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `speech`
- **Instruments:** speech, music, effects
- **Best result:** Multi-stem: speech, music, effects
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bandit_last_config.yaml

### Bandit — Plus (ep 30) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `bandit_30_zfturbo.ckpt`
- **Config:** `bandit_30_zfturbo_config.yaml`
- **Architecture:** Bandit
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `speech`
- **Instruments:** speech, music, effects
- **Best result:** Multi-stem: speech, music, effects
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bandit_30_zfturbo_config.yaml

### Bandit — Plus (ep 57) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `bandit_57_zfturbo.ckpt`
- **Config:** `bandit_57_zfturbo_config.yaml`
- **Architecture:** Bandit
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `speech`
- **Instruments:** speech, music, effects
- **Best result:** Multi-stem: speech, music, effects
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bandit_57_zfturbo_config.yaml

### Bandit — Plus (ep 63) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `bandit_63_zfturbo.ckpt`
- **Config:** `bandit_63_zfturbo_config.yaml`
- **Architecture:** Bandit
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `speech`
- **Instruments:** speech, music, effects
- **Best result:** Multi-stem: speech, music, effects
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:bandit_63_zfturbo_config.yaml

### Bandit — Cinematic Bandit Plus · kwatcharasupat

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

### Bandit — Cinematic Bandit v2 Multilang · kwatcharasupat

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

### MDX-Net — UVR Instrumental Full 292

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET-Inst_full_292.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.1), vocals (8.5)

### MDX-Net — UVR Instrumental 187 Beta

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Inst_187_beta.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (14.3), vocals (8.5)

### MDX-Net — UVR Instrumental 82 Beta

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Inst_82_beta.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (14.3), vocals (8.2)

### MDX-Net — UVR Instrumental 90 Beta

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Inst_90_beta.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.9), vocals (8.1)

### MDX-Net — UVR Main 340

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Main_340.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** instrumental, vocals
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.2), instrumental (15.4)

### MDX-Net — UVR Main 390

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Main_390.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** instrumental, vocals
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (4.5), instrumental (8.8)

### MDX-Net — UVR Main 406

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Main_406.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** instrumental, vocals
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.4), instrumental (15.3)

### MDX-Net — UVR Main 427

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Main_427.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** instrumental, vocals
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.2), instrumental (15.5)

### MDX-Net — UVR Main 438

- **Source:** TRvlvr
- **Weight:** `UVR-MDX-NET_Main_438.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** instrumental, vocals
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.1), instrumental (15.3)

### MDX-Net — Kim Instrumental

- **Source:** TRvlvr+Politrees
- **Weight:** `Kim_Inst.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.5), vocals (9.1)

### MDX-Net — Kim Vocals 1

- **Source:** TRvlvr+Politrees
- **Weight:** `Kim_Vocal_1.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.1), instrumental (15.5)

### MDX-Net — Kim Vocals 2

- **Source:** TRvlvr+Politrees
- **Weight:** `Kim_Vocal_2.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.2), instrumental (15.4)

### MDX-Net — Reverb HQ · FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `Reverb_HQ_By_FoxJoy.onnx`
- **Name intent:** special_fx
- **Backend focus:** special_fx_primary:reverb
- **Primary stem (backend):** `reverb`
- **Best result:** Reverb (isolated reverb stem)
- **Save stems UI:** UI: reverb / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: reverb*, no reverb

### MDX-Net — UVR 1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_1_9703.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.6), instrumental (15.0)

### MDX-Net — UVR 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_2_9682.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.4), instrumental (15.0)

### MDX-Net — UVR 3

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_3_9662.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.7), instrumental (15.0)

### MDX-Net — UVR Crowd HQ 1 · Aufr33

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET_Crowd_HQ_1.onnx`
- **Name intent:** special_fx
- **Backend focus:** special_fx_primary:no crowd
- **Primary stem (backend):** `no crowd`
- **Best result:** no crowd (mix minus crowd)
- **Save stems UI:** UI: no crowd / complement stem
- **Metadata:** community_models.txt
- **Note:** Community ref: no crowd*, crowd

### MDX-Net — UVR Instrumental 1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_1.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.2), vocals (9.2)

### MDX-Net — UVR Instrumental 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_2.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.3), vocals (9.2)

### MDX-Net — UVR Instrumental 3

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_3.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.3), vocals (9.2)

### MDX-Net — UVR Instrumental HQ 1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_1.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.4), vocals (8.8)

### MDX-Net — UVR Instrumental HQ 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_2.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.3), vocals (8.8)

### MDX-Net — UVR Instrumental HQ 3

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_3.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.4), vocals (8.8)

### MDX-Net — UVR Instrumental HQ 4

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_4.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.5), vocals (8.8)

### MDX-Net — UVR Instrumental HQ 5

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_5.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.3), vocals (8.7)

### MDX-Net — UVR Instrumental Main

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_Main.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** instrumental, vocals
- **Target instrument:** `instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.1), vocals (8.5)

### MDX-Net — UVR Karaoke

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_KARA.onnx`
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (5.6), instrumental (14.1)

### MDX-Net — UVR Karaoke 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_KARA_2.onnx`
- **Name intent:** karaoke
- **Backend focus:** karaoke_instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (14.8), vocals (5.4)

### MDX-Net — UVR Main

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_Main.onnx`
- **Name intent:** dual_voc_inst
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** instrumental, vocals
- **Target instrument:** `vocals`
- **Best result:** Vocals or Instrumental — both are first-class 2-stem exports
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** community_models.txt
- **Note:** Both Vocals and Instrumental are first-class exports
- **Note:** Community ref: vocals* (10.2), instrumental (15.4)

### MDX-Net — UVR Vocals Fine-Tuned

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Voc_FT.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** instrumental, vocals
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.2), instrumental (15.4)

### MDX-Net — UVR 9482

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_9482.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.3), instrumental (14.9)

### MDX-Net — KUIELAB A Bass

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_bass.onnx`
- **Name intent:** multi_stem
- **Backend focus:** demucs_component:bass
- **Primary stem (backend):** `bass`
- **Best result:** Kuielab Demucs bass stem (single 4-stem component)
- **Metadata:** community_models.txt
- **Note:** Community ref: bass* (10.4), no bass

### MDX-Net — KUIELAB A Drums

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_drums.onnx`
- **Name intent:** multi_stem
- **Backend focus:** demucs_component:drums
- **Primary stem (backend):** `drums`
- **Best result:** Kuielab Demucs drums stem (single 4-stem component)
- **Metadata:** community_models.txt
- **Note:** Community ref: drums* (7.0), no drums

### MDX-Net — KUIELAB A Other

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_other.onnx`
- **Name intent:** multi_stem
- **Backend focus:** demucs_component:other
- **Primary stem (backend):** `other`
- **Best result:** Kuielab Demucs other stem (single 4-stem component)
- **Metadata:** community_models.txt
- **Note:** Community ref: other*, no other

### MDX-Net — KUIELAB A Vocals

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_vocals.onnx`
- **Name intent:** multi_stem
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.6), instrumental (15.3)

### MDX-Net — KUIELAB B Bass

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_bass.onnx`
- **Name intent:** multi_stem
- **Backend focus:** demucs_component:bass
- **Primary stem (backend):** `bass`
- **Best result:** Kuielab Demucs bass stem (single 4-stem component)
- **Metadata:** community_models.txt
- **Note:** Community ref: bass* (9.9), no bass

### MDX-Net — KUIELAB B Drums

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_drums.onnx`
- **Name intent:** multi_stem
- **Backend focus:** demucs_component:drums
- **Primary stem (backend):** `drums`
- **Best result:** Kuielab Demucs drums stem (single 4-stem component)
- **Metadata:** community_models.txt
- **Note:** Community ref: drums* (7.1), no drums

### MDX-Net — KUIELAB B Other

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_other.onnx`
- **Name intent:** multi_stem
- **Backend focus:** demucs_component:other
- **Primary stem (backend):** `other`
- **Best result:** Kuielab Demucs other stem (single 4-stem component)
- **Metadata:** community_models.txt
- **Note:** Community ref: other*, no other

### MDX-Net — KUIELAB B Vocals

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_vocals.onnx`
- **Name intent:** multi_stem
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.0), instrumental (15.1)

## MDX-Net (detail)

### MDX23C — Small (4 Stems) · KUIELAB

- **Source:** mvsepless
- **Weight:** `mdx23c_4stem_small_kuielab.ckpt`
- **Config:** `mdx23c_4stem_small_kuielab_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, drums, bass, other
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mdx23c_4stem_small_kuielab_config.yaml

### MDX23C (4 Stems) · KUIELAB

- **Source:** mvsepless
- **Weight:** `mdx23c_4stem_kuielab.ckpt`
- **Config:** `mdx23c_4stem_kuielab_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, drums, bass, other
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mdx23c_4stem_kuielab_config.yaml

### MDX23C (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `mdx23c_4stem_zfturbo.ckpt`
- **Config:** `mdx23c_4stem_zfturbo_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, bass, drums, other
- **Best result:** Multi-stem: vocals, bass, drums, other
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mdx23c_4stem_zfturbo_config.yaml

### MDX23C — 8K FFT Instrumental/Vocals HQ v1

- **Source:** mvsepless
- **Weight:** `mdx23c_instvoc_hq1.ckpt`
- **Config:** `mdx23c_instvoc_hq1_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:mdx23c_instvoc_hq1_config.yaml

### MDX23C — 8K FFT Instrumental/Vocals HQ v2

- **Source:** mvsepless
- **Weight:** `mdx23c_instvoc_hq2.ckpt`
- **Config:** `mdx23c_instvoc_hq2_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:mdx23c_instvoc_hq2_config.yaml

### MDX23C — DrumSep (5 Stems) · Aufr33 & Jarredou

- **Source:** mvsepless
- **Weight:** `mdx23c_drumsep_5stem_aufr33_jarredou.ckpt`
- **Config:** `mdx23c_drumsep_5stem_aufr33_jarredou_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `kick`
- **Instruments:** kick, snare, toms, hh, cymbals
- **Best result:** Multi-stem: kick, snare, toms, hh, cymbals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mdx23c_drumsep_5stem_aufr33_jarredou_config.yaml

### MDX23C — DrumSep (6 Stems) · Aufr33 & Jarredou

- **Source:** mvsepless
- **Weight:** `mdx23c_drumsep_6stem_aufr33_jarredou.ckpt`
- **Config:** `mdx23c_drumsep_6stem_aufr33_jarredou_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `kick`
- **Instruments:** kick, snare, toms, hh, ride, crash
- **Best result:** Multi-stem: kick, snare, toms, hh, ride, crash
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mdx23c_drumsep_6stem_aufr33_jarredou_config.yaml

### MDX23C — Instrumental/Vocals HQ · ZFTurbo

- **Source:** mvsepless
- **Weight:** `mdx23c_instvoc_zfturbo.ckpt`
- **Config:** `mdx23c_instvoc_zfturbo_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mdx23c_instvoc_zfturbo_config.yaml

### MDX23C — Mid-Side · WesleyR36

- **Source:** mvsepless
- **Weight:** `mdx23c_mid_side_wesleyr36.ckpt`
- **Config:** `mdx23c_mid_side_wesleyr36_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** spatial
- **Backend focus:** specialty_target:similarity
- **Primary stem (backend):** `similarity`
- **Instruments:** similarity, difference
- **Target instrument:** `similarity`
- **Best result:** similarity (single native output)
- **Metadata:** bundled_yaml:mdx23c_mid_side_wesleyr36_config.yaml

### MDX23C — Mid-Side v1 · Gilliaaan

- **Source:** mvsepless
- **Weight:** `mdx23c_mid_side_gilliaaan.ckpt`
- **Config:** `mdx23c_mid_side_gilliaaan_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** spatial
- **Backend focus:** single_target:wide
- **Primary stem (backend):** `wide`
- **Instruments:** center, wide
- **Target instrument:** `wide`
- **Best result:** wide (single native output)
- **Metadata:** bundled_yaml:mdx23c_mid_side_gilliaaan_config.yaml

### MDX23C — Mid-Side v2e · Gilliaaan

- **Source:** mvsepless
- **Weight:** `mdx23c_mid_side2e_gilliaaan.ckpt`
- **Config:** `mdx23c_mid_side2e_gilliaaan_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** spatial
- **Backend focus:** two_stem
- **Primary stem (backend):** `center`
- **Instruments:** center, wide
- **Best result:** center, wide
- **Metadata:** bundled_yaml:mdx23c_mid_side2e_gilliaaan_config.yaml

## MDX23C (detail)

### MDX23C — 8K FFT Instrumental/Vocals HQ 2

- **Source:** TRvlvr
- **Weight:** `MDX23C-8KFFT-InstVoc_HQ_2.ckpt`
- **Name intent:** dual_voc_inst
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals (10.5), instrumental (15.9)

### MDX23C — DeReverb · Aufr33 & Jarredou

- **Source:** Politrees
- **Weight:** `MDX23C-De-Reverb-aufr33-jarredou.ckpt`
- **Config:** `config_dereverb_mdx23c.yaml`
- **Architecture:** MDX23C
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, No dry
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_dereverb_mdx23c.yaml
- **Note:** Community ref: dry, no dry

### MDX23C — DrumSep · Aufr33 & Jarredou

- **Source:** Politrees
- **Weight:** `MDX23C-DrumSep-aufr33-jarredou.ckpt`
- **Config:** `config_drumsep_mdx23c.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `kick`
- **Instruments:** kick, snare, toms, hh, ride, crash
- **Best result:** Multi-stem: kick, snare, toms, hh, ride, crash
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_drumsep_mdx23c.yaml
- **Note:** Community ref: kick, snare, toms, hh, ride, crash

### MDX23C — Phantom Centre Extraction · WesleyR36

- **Source:** Politrees
- **Weight:** `model_mdx23c_ep_271_l1_freq_72.2383.ckpt`
- **Config:** `config_mdx23c_similarity.yaml`
- **Architecture:** MDX23C
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:Similarity
- **Primary stem (backend):** `Similarity`
- **Instruments:** Similarity, Difference
- **Target instrument:** `Similarity`
- **Best result:** Similarity, Difference
- **Save stems UI:** UI: Similarity / Difference subset
- **Metadata:** bundled_yaml:config_mdx23c_similarity.yaml

### MDX23C — 8K FFT Instrumental/Vocals HQ

- **Source:** TRvlvr
- **Weight:** `MDX23C-8KFFT-InstVoc_HQ.ckpt`
- **Name intent:** dual_voc_inst
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals (10.6), instrumental (15.8)

### MDX23C — D1581

- **Source:** TRvlvr
- **Weight:** `MDX23C_D1581.ckpt`
- **Name intent:** vocals
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Instrumental, Vocals
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals (10.0), instrumental (15.5)
- **⚠ Flags:** NAME says vocals but backend is not vocal-focused

## MDX-Net (detail)

### MDX23C — Orchestra Experimental · Verosment

- **Source:** mvsepless
- **Weight:** `mdx23c_orch_verosment.ckpt`
- **Config:** `mdx23c_orch_verosment_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** instrument_target:orch
- **Backend focus:** single_target:orch
- **Primary stem (backend):** `orch`
- **Instruments:** inst, orch
- **Target instrument:** `orch`
- **Best result:** orch (single native output)
- **Metadata:** bundled_yaml:mdx23c_orch_verosment_config.yaml

### MDX23C — SFX Splitter · Jasper

- **Source:** mvsepless
- **Weight:** `mdx23c_sfxsplitter_jasper.ckpt`
- **Config:** `mdx23c_sfxsplitter_jasper_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** two_stem
- **Primary stem (backend):** `foreground`
- **Instruments:** foreground, background
- **Best result:** Multi-stem: foreground, background
- **Metadata:** bundled_yaml:mdx23c_sfxsplitter_jasper_config.yaml

### MDX23C — SFX · Jasper

- **Source:** mvsepless
- **Weight:** `mdx23c_sfx_jasper.ckpt`
- **Config:** `mdx23c_sfx_jasper_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** two_stem
- **Primary stem (backend):** `foreground`
- **Instruments:** foreground, background
- **Best result:** Multi-stem: foreground, background
- **Metadata:** bundled_yaml:mdx23c_sfx_jasper_config.yaml

### MDX23C — Vocals · KUIELAB

- **Source:** mvsepless
- **Weight:** `mdx23c_vocals_kuielab.ckpt`
- **Config:** `mdx23c_vocals_kuielab_config.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mdx23c_vocals_kuielab_config.yaml

### MelBand Roformer — Large (4 Stems) · Aname

- **Source:** mvsepless
- **Weight:** `mbr_4stemlarge1_aname.ckpt`
- **Config:** `mbr_4stemlarge1_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mbr_4stemlarge1_aname_config.yaml

### MelBand Roformer — XL (4 Stems) · Aname

- **Source:** mvsepless
- **Weight:** `mbr_4stemxl1_aname.ckpt`
- **Config:** `mbr_4stemxl1_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mbr_4stemxl1_aname_config.yaml

### MelBand Roformer — Large v2 (4 Stems) · Aname

- **Source:** mvsepless
- **Weight:** `mbr_4stemlarge2_aname.ckpt`
- **Config:** `mbr_4stemlarge2_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:mbr_4stemlarge2_aname_config.yaml

### MelBand Roformer — Ambiance · jazzpear

- **Source:** mvsepless
- **Weight:** `mbr_amb_jazzpear.ckpt`
- **Config:** `mbr_amb_jazzpear_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** single_target:ambience
- **Primary stem (backend):** `ambience`
- **Instruments:** ambience, other
- **Target instrument:** `ambience`
- **Best result:** ambience (single native output)
- **Metadata:** bundled_yaml:mbr_amb_jazzpear_config.yaml

### MelBand Roformer — BGM · Jasper

- **Source:** mvsepless
- **Weight:** `mbr_bgm_jasper.ckpt`
- **Config:** `mbr_bgm_jasper_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bgm_jasper_config.yaml

### MelBand Roformer — Karaoke BVE · Gonzaluigi

- **Source:** mvsepless
- **Weight:** `mbr_bve_gonzaluigi.ckpt`
- **Config:** `mbr_bve_gonzaluigi_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:Lead
- **Primary stem (backend):** `Lead`
- **Instruments:** Lead, Back
- **Target instrument:** `Lead`
- **Best result:** Lead, Back
- **Save stems UI:** UI: Lead / Back subset
- **Metadata:** bundled_yaml:mbr_bve_gonzaluigi_config.yaml

### MelBand Roformer — Big Beta v1 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta1_unwa.ckpt`
- **Config:** `mbr_bigbeta1_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta1_unwa_config.yaml

### MelBand Roformer — Big Beta v2 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta2_unwa.ckpt`
- **Config:** `mbr_bigbeta2_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta2_unwa_config.yaml

### MelBand Roformer — Big Beta v3 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta3_unwa.ckpt`
- **Config:** `mbr_bigbeta3_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta3_unwa_config.yaml

### MelBand Roformer — Big Beta v4 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta4_unwa.ckpt`
- **Config:** `mbr_bigbeta4_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta4_unwa_config.yaml

### MelBand Roformer — Big Beta v6 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta6_unwa.ckpt`
- **Config:** `mbr_bigbeta6_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta6_unwa_config.yaml

### MelBand Roformer — Big Beta v6x · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta6x_unwa.ckpt`
- **Config:** `mbr_bigbeta6x_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta6x_unwa_config.yaml

### MelBand Roformer — Big Beta v7 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta7_unwa.ckpt`
- **Config:** `mbr_bigbeta7_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta7_unwa_config.yaml

### MelBand Roformer — Big SYHFT v1 Fast · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_bigsyhft1fast.ckpt`
- **Config:** `mbr_bigsyhft1fast_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigsyhft1fast_config.yaml

### MelBand Roformer — DeBigReverb · Sucial

- **Source:** mvsepless
- **Weight:** `mbr_debigreverb_sucial.ckpt`
- **Config:** `mbr_debigreverb_sucial_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** removal:reverb
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:mbr_debigreverb_sucial_config.yaml

### MelBand Roformer — DeNoise Aggressive · Aufr33

- **Source:** mvsepless
- **Weight:** `mbr_denoise_aggr_aufr33.ckpt`
- **Config:** `mbr_denoise_aggr_aufr33_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:mbr_denoise_aggr_aufr33_config.yaml

### MelBand Roformer — DeNoise · Yuluoye

- **Source:** mvsepless
- **Weight:** `mbr_denoise_yuluoye.ckpt`
- **Config:** `mbr_denoise_yuluoye_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `other`
- **Instruments:** dry, other
- **Target instrument:** `other`
- **Best result:** other (post-processing stem)
- **Save stems UI:** UI: other / complement stem
- **Metadata:** bundled_yaml:mbr_denoise_yuluoye_config.yaml

### MelBand Roformer — DeNoiser Children 16 kHz · Phaedrus33

- **Source:** mvsepless
- **Weight:** `mbr_denoise_children_phaedrus33.ckpt`
- **Config:** `mbr_denoise_children_phaedrus33_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:speech
- **Primary stem (backend):** `speech`
- **Instruments:** speech, noise
- **Target instrument:** `speech`
- **Best result:** speech (post-processing stem)
- **Save stems UI:** UI: speech / complement stem
- **Metadata:** bundled_yaml:mbr_denoise_children_phaedrus33_config.yaml

### MelBand Roformer — DeUX · Becruily

- **Source:** mvsepless
- **Weight:** `mbr_deux_becruily.ckpt`
- **Config:** `mbr_deux_becruily_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** bundled_yaml:mbr_deux_becruily_config.yaml

### MelBand Roformer — DeNoise DeBleed · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_denoise_debleed_gabox.ckpt`
- **Config:** `mbr_denoise_debleed_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_denoise_debleed_gabox_config.yaml
- **Note:** Name intent corrected from metadata (instrumental)

### MelBand Roformer — Duet · Dry Paint Dealer Undr

- **Source:** mvsepless
- **Weight:** `mbr_duet_drypaint.ckpt`
- **Config:** `mbr_duet_drypaint_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** two_stem
- **Primary stem (backend):** `singer_1`
- **Instruments:** singer_1, singer_2
- **Best result:** singer_1, singer_2
- **Metadata:** bundled_yaml:mbr_duet_drypaint_config.yaml

### MelBand Roformer — Explosions · jazzpear

- **Source:** mvsepless
- **Weight:** `mbr_expl_jazzpear.ckpt`
- **Config:** `mbr_expl_jazzpear_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** single_target:explosions
- **Primary stem (backend):** `explosions`
- **Instruments:** explosions, other
- **Target instrument:** `explosions`
- **Best result:** explosions (single native output)
- **Metadata:** bundled_yaml:mbr_expl_jazzpear_config.yaml

### MelBand Roformer — Fighting · jazzpear

- **Source:** mvsepless
- **Weight:** `mbr_fight_jazzpear.ckpt`
- **Config:** `mbr_fight_jazzpear_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** single_target:fighting
- **Primary stem (backend):** `fighting`
- **Instruments:** fighting, other
- **Target instrument:** `fighting`
- **Best result:** fighting (single native output)
- **Metadata:** bundled_yaml:mbr_fight_jazzpear_config.yaml

### MelBand Roformer — Foley · jazzpear

- **Source:** mvsepless
- **Weight:** `mbr_misc_jazzpear.ckpt`
- **Config:** `mbr_misc_jazzpear_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** single_target:foley
- **Primary stem (backend):** `foley`
- **Instruments:** foley, other
- **Target instrument:** `foley`
- **Best result:** foley (single native output)
- **Metadata:** bundled_yaml:mbr_misc_jazzpear_config.yaml

### MelBand Roformer — Footsteps · jazzpear

- **Source:** mvsepless
- **Weight:** `mbr_foot_jazzpear.ckpt`
- **Config:** `mbr_foot_jazzpear_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** single_target:footsteps
- **Primary stem (backend):** `footsteps`
- **Instruments:** footsteps, other
- **Target instrument:** `footsteps`
- **Best result:** footsteps (single native output)
- **Metadata:** bundled_yaml:mbr_foot_jazzpear_config.yaml

### MelBand Roformer — General · jazzpear

- **Source:** mvsepless
- **Weight:** `mbr_gen_jazzpear.ckpt`
- **Config:** `mbr_gen_jazzpear_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_gen_jazzpear_config.yaml

### MelBand Roformer — Guitar · chenCFD

- **Source:** mvsepless
- **Weight:** `mbr_guitar_chencfd.ckpt`
- **Config:** `mbr_guitar_chencfd_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:guitar
- **Primary stem (backend):** `guitar`
- **Instruments:** guitar, others
- **Target instrument:** `guitar`
- **Best result:** guitar, others
- **Save stems UI:** UI: guitar / others subset
- **Metadata:** bundled_yaml:mbr_guitar_chencfd_config.yaml

### MelBand Roformer — Hybrid Arch · Aname

- **Source:** mvsepless
- **Weight:** `mbr_hybrid_arch_aname.ckpt`
- **Config:** `mbr_hybrid_arch_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** two_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_hybrid_arch_aname_config.yaml

### MelBand Roformer — Instrumental Rifforge · Mesk

- **Source:** mvsepless
- **Weight:** `mbr_inst_rifforge_meskvlla33.ckpt`
- **Config:** `mbr_inst_rifforge_meskvlla33_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_inst_rifforge_meskvlla33_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Instrumental VFX · neoculture

- **Source:** mvsepless
- **Weight:** `mbr_neo_inst_vfx.ckpt`
- **Config:** `mbr_neo_inst_vfx_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_neo_inst_vfx_config.yaml

### MelBand Roformer — Instrumental/Vocals Duality v1 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_instvoc_duality1_unwa.ckpt`
- **Config:** `mbr_instvoc_duality1_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:mbr_instvoc_duality1_unwa_config.yaml

### MelBand Roformer — Instrumental/Vocals Duality v2 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_instvoc_duality2_unwa.ckpt`
- **Config:** `mbr_instvoc_duality2_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:mbr_instvoc_duality2_unwa_config.yaml

### MelBand Roformer — Instrumental Bv1 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instbv1_gabox.ckpt`
- **Config:** `mbr_instbv1_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instbv1_gabox_config.yaml

### MelBand Roformer — Instrumental Bv2 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instbv2_gabox.ckpt`
- **Config:** `mbr_instbv2_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instbv2_gabox_config.yaml

### MelBand Roformer — Instrumental Bv3 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instbv3_gabox.ckpt`
- **Config:** `mbr_instbv3_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instbv3_gabox_config.yaml

### MelBand Roformer — Instrumental Flowers v10 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instflowersv10_gabox.ckpt`
- **Config:** `mbr_instflowersv10_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_instflowersv10_gabox_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Instrumental Fv1 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv1_gabox.ckpt`
- **Config:** `mbr_instfv1_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv1_gabox_config.yaml

### MelBand Roformer — Instrumental Fv10 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv10_gabox.ckpt`
- **Config:** `mbr_instfv10_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv10_gabox_config.yaml

### MelBand Roformer — Instrumental Fv2 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv2_gabox.ckpt`
- **Config:** `mbr_instfv2_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv2_gabox_config.yaml

### MelBand Roformer — Instrumental Fv3 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv3_gabox.ckpt`
- **Config:** `mbr_instfv3_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv3_gabox_config.yaml

### MelBand Roformer — Instrumental Fv4 Noise · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv4n_gabox.ckpt`
- **Config:** `mbr_instfv4n_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv4n_gabox_config.yaml

### MelBand Roformer — Instrumental Fv4 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv4_gabox.ckpt`
- **Config:** `mbr_instfv4_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv4_gabox_config.yaml

### MelBand Roformer — Instrumental Fv5 Noise · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv5n_gabox.ckpt`
- **Config:** `mbr_instfv5n_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv5n_gabox_config.yaml

### MelBand Roformer — Instrumental Fv5 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv5_gabox.ckpt`
- **Config:** `mbr_instfv5_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv5_gabox_config.yaml

### MelBand Roformer — Instrumental Fv6 Noise · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv6n_gabox.ckpt`
- **Config:** `mbr_instfv6n_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv6n_gabox_config.yaml

### MelBand Roformer — Instrumental Fv6 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv6_gabox.ckpt`
- **Config:** `mbr_instfv6_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv6_gabox_config.yaml

### MelBand Roformer — Instrumental Fv7 Noise · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv7n_gabox.ckpt`
- **Config:** `mbr_instfv7n_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv7n_gabox_config.yaml

### MelBand Roformer — Instrumental Fv7 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv7_gabox.ckpt`
- **Config:** `mbr_instfv7_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv7_gabox_config.yaml

### MelBand Roformer — Instrumental Fv7+ · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv7+_gabox.ckpt`
- **Config:** `mbr_instfv7+_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv7+_gabox_config.yaml

### MelBand Roformer — Instrumental Fv7z · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv7z_gabox.ckpt`
- **Config:** `mbr_instfv7z_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv7z_gabox_config.yaml

### MelBand Roformer — Instrumental Fv8 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv8_gabox.ckpt`
- **Config:** `mbr_instfv8_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv8_gabox_config.yaml

### MelBand Roformer — Instrumental Fv8b · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfv8b_gabox.ckpt`
- **Config:** `mbr_instfv8b_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv8b_gabox_config.yaml

### MelBand Roformer — Instrumental Fv9 · GaboxR67 [mbr_instfv9_2_gabox]

- **Source:** mvsepless
- **Weight:** `mbr_instfv9_2_gabox.ckpt`
- **Config:** `mbr_instfv9_2_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv9_2_gabox_config.yaml

### MelBand Roformer — Instrumental Fv9 · GaboxR67 [mbr_instfv9_gabox]

- **Source:** mvsepless
- **Weight:** `mbr_instfv9_gabox.ckpt`
- **Config:** `mbr_instfv9_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfv9_gabox_config.yaml

### MelBand Roformer — Instrumental FvX · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_instfvx_gabox.ckpt`
- **Config:** `mbr_instfvx_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_instfvx_gabox_config.yaml

### MelBand Roformer — Instrumental · Becruily [mbr_guitar_becruily]

- **Source:** mvsepless
- **Weight:** `mbr_guitar_becruily.ckpt`
- **Config:** `mbr_guitar_becruily_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** specialty_target:Guitar
- **Primary stem (backend):** `Guitar`
- **Instruments:** Guitar, Other
- **Target instrument:** `Guitar`
- **Best result:** Guitar (single native output)
- **Metadata:** bundled_yaml:mbr_guitar_becruily_config.yaml

### MelBand Roformer — Instrumental · Becruily [mbr_inst_becruily]

- **Source:** mvsepless
- **Weight:** `mbr_inst_becruily.ckpt`
- **Config:** `mbr_inst_becruily_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_inst_becruily_config.yaml

### MelBand Roformer — Instrumental (SDR 16.52) · Essid

- **Source:** mvsepless
- **Weight:** `mbr_inst_1652_essid.ckpt`
- **Config:** `mbr_inst_1652_essid_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_inst_1652_essid_config.yaml

### MelBand Roformer — Instrumental (SDR 16.81) · Essid

- **Source:** mvsepless
- **Weight:** `mbr_inst_1681_essid.ckpt`
- **Config:** `mbr_inst_1681_essid_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:mbr_inst_1681_essid_config.yaml

### MelBand Roformer — Instrumental v1 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_inst1_unwa.ckpt`
- **Config:** `mbr_inst1_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_inst1_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Instrumental v1+ · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_inst1+_unwa.ckpt`
- **Config:** `mbr_inst1+_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_inst1+_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Instrumental v1e Plus · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_inst1e+_unwa.ckpt`
- **Config:** `mbr_inst1e+_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_inst1e+_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Instrumental v1e · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_inst1e_unwa.ckpt`
- **Config:** `mbr_inst1e_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_inst1e_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Instrumental v2 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_inst2_unwa.ckpt`
- **Config:** `mbr_inst2_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_inst2_unwa_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Karaoke 25-02-2025 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_karaoke25022025_gabox.ckpt`
- **Config:** `mbr_karaoke25022025_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_unknown_primary
- **Primary stem (backend):** `karaoke`
- **Instruments:** karaoke, other
- **Target instrument:** `karaoke`
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Metadata:** bundled_yaml:mbr_karaoke25022025_gabox_config.yaml

### MelBand Roformer — Karaoke 28-02-2025 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_karaoke28022025_gabox.ckpt`
- **Config:** `mbr_karaoke28022025_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_unknown_primary
- **Primary stem (backend):** `karaoke`
- **Instruments:** karaoke, other
- **Target instrument:** `karaoke`
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Metadata:** bundled_yaml:mbr_karaoke28022025_gabox_config.yaml

### MelBand Roformer — Karaoke Fusion Aggressive · Gonzaluigi [mbr_karaoke_fusion2_aggr_gonzaluigi]

- **Source:** mvsepless
- **Weight:** `mbr_karaoke_fusion2_aggr_gonzaluigi.ckpt`
- **Config:** `mbr_karaoke_fusion2_aggr_gonzaluigi_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_karaoke_fusion2_aggr_gonzaluigi_config.yaml

### MelBand Roformer — Karaoke Fusion Aggressive · Gonzaluigi [mbr_karaoke_fusion_aggr_gonzaluigi]

- **Source:** mvsepless
- **Weight:** `mbr_karaoke_fusion_aggr_gonzaluigi.ckpt`
- **Config:** `mbr_karaoke_fusion_aggr_gonzaluigi_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_karaoke_fusion_aggr_gonzaluigi_config.yaml

### MelBand Roformer — Karaoke Fusion Total · Gonzaluigi

- **Source:** mvsepless
- **Weight:** `mbr_karaoke_fusion_total_aggr_gonzaluigi.ckpt`
- **Config:** `mbr_karaoke_fusion_total_aggr_gonzaluigi_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_karaoke_fusion_total_aggr_gonzaluigi_config.yaml

### MelBand Roformer — Karaoke Fusion · Gonzaluigi

- **Source:** mvsepless
- **Weight:** `mbr_karaoke_fusion_gonzaluigi.ckpt`
- **Config:** `mbr_karaoke_fusion_gonzaluigi_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_karaoke_fusion_gonzaluigi_config.yaml

### MelBand Roformer — Karaoke Small · GaboxR67 & Aufr33

- **Source:** mvsepless
- **Weight:** `mbr_karaoke_small_gabox_aufr33.ckpt`
- **Config:** `mbr_karaoke_small_gabox_aufr33_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_karaoke_small_gabox_aufr33_config.yaml

### MelBand Roformer — Karaoke v1 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_karaoke1_gabox.ckpt`
- **Config:** `mbr_karaoke1_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_karaoke1_gabox_config.yaml

### MelBand Roformer — Karaoke v2 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_karaoke2_gabox.ckpt`
- **Config:** `mbr_karaoke2_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_karaoke2_gabox_config.yaml

### MelBand Roformer — Kim Fine-Tuned v1 · Aname

- **Source:** mvsepless
- **Weight:** `mbr_kimft1_aname.ckpt`
- **Config:** `mbr_kimft1_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_kimft1_aname_config.yaml

### MelBand Roformer — Kim Fine-Tuned v1 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_kimft1_unwa.ckpt`
- **Config:** `mbr_kimft1_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_kimft1_unwa_config.yaml

### MelBand Roformer — Kim Fine-Tuned v2 Fullness · Aname

- **Source:** mvsepless
- **Weight:** `mbr_kimft2f_aname.ckpt`
- **Config:** `mbr_kimft2f_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_kimft2f_aname_config.yaml

### MelBand Roformer — Kim Fine-Tuned v2 · Aname

- **Source:** mvsepless
- **Weight:** `mbr_kimft2_aname.ckpt`
- **Config:** `mbr_kimft2_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_kimft2_aname_config.yaml

### MelBand Roformer — Kim Fine-Tuned v3 · Aname

- **Source:** mvsepless
- **Weight:** `mbr_kimft3_aname.ckpt`
- **Config:** `mbr_kimft3_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_kimft3_aname_config.yaml

### MelBand Roformer — Kim Fine-Tuned v3 Preview · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_kimft3_prev_unwa.ckpt`
- **Config:** `mbr_kimft3_prev_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_kimft3_prev_unwa_config.yaml

### MelBand Roformer — Lead Vocals DeReverb · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_leadvoc_dereverb_gabox.ckpt`
- **Config:** `mbr_leadvoc_dereverb_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_leadvoc_dereverb_gabox_config.yaml

### MelBand Roformer — Lead-Rhythm Guitar · listra92

- **Source:** mvsepless
- **Weight:** `mbr_lead_rhythm_guitar_listra92.ckpt`
- **Config:** `mbr_lead_rhythm_guitar_listra92_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:Lead
- **Primary stem (backend):** `Lead`
- **Instruments:** Lead, Rhythm
- **Target instrument:** `Lead`
- **Best result:** Lead, Rhythm
- **Save stems UI:** UI: Lead / Rhythm subset
- **Metadata:** bundled_yaml:mbr_lead_rhythm_guitar_listra92_config.yaml

### MelBand Roformer — Merged Beta v1 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhftbeta1.ckpt`
- **Config:** `mbr_syhftbeta1_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhftbeta1_config.yaml

### MelBand Roformer — Metal Instrumental Preview · Mesk

- **Source:** mvsepless
- **Weight:** `mbr_inst_metal_prev_meskvlla33.ckpt`
- **Config:** `mbr_inst_metal_prev_meskvlla33_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_inst_metal_prev_meskvlla33_config.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer — Mid-Side · Gilliaaan

- **Source:** mvsepless
- **Weight:** `mbr_mid_side_gilliaaan.ckpt`
- **Config:** `mbr_mid_side_gilliaaan_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** spatial
- **Backend focus:** two_stem
- **Primary stem (backend):** `mid`
- **Instruments:** mid, side
- **Best result:** mid, side
- **Metadata:** bundled_yaml:mbr_mid_side_gilliaaan_config.yaml

### MelBand Roformer — Musicless · Jasper

- **Source:** mvsepless
- **Weight:** `mbr_musicless_jasper.ckpt`
- **Config:** `mbr_musicless_jasper_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** single_target:nomusic
- **Primary stem (backend):** `nomusic`
- **Instruments:** nomusic, music
- **Target instrument:** `nomusic`
- **Best result:** Multi-stem: nomusic, music
- **Metadata:** bundled_yaml:mbr_musicless_jasper_config.yaml

### MelBand Roformer — Percussion Experimental · yolkispalkis

- **Source:** mvsepless
- **Weight:** `mbr_percussion_yolkispaliks.ckpt`
- **Config:** `mbr_percussion_yolkispaliks_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrument_target:percussion
- **Backend focus:** single_target:percussions
- **Primary stem (backend):** `percussions`
- **Instruments:** percussions, other
- **Target instrument:** `percussions`
- **Best result:** percussions (single native output)
- **Metadata:** bundled_yaml:mbr_percussion_yolkispaliks_config.yaml

### MelBand Roformer — SYHFT B1 1 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhftB1_1.ckpt`
- **Config:** `mbr_syhftB1_1_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhftB1_1_config.yaml

### MelBand Roformer — SYHFT B1 2 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhftB1_2.ckpt`
- **Config:** `mbr_syhftB1_2_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhftB1_2_config.yaml

### MelBand Roformer — SYHFT B1 3 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhftB1_3.ckpt`
- **Config:** `mbr_syhftB1_3_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhftB1_3_config.yaml

### MelBand Roformer — SYHFT v1 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhft1.ckpt`
- **Config:** `mbr_syhft1_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhft1_config.yaml

### MelBand Roformer — SYHFT v2 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhft2.ckpt`
- **Config:** `mbr_syhft2_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhft2_config.yaml

### MelBand Roformer — SYHFT v2.5 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhft2.5.ckpt`
- **Config:** `mbr_syhft2.5_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhft2.5_config.yaml

### MelBand Roformer — SYHFT v3 · SYH99999

- **Source:** mvsepless
- **Weight:** `mbr_syhft3.ckpt`
- **Config:** `mbr_syhft3_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_syhft3_config.yaml

### MelBand Roformer — Scratch Large · Aname

- **Source:** mvsepless
- **Weight:** `mbr_scratch_aname.ckpt`
- **Config:** `mbr_scratch_aname_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_scratch_aname_config.yaml

### MelBand Roformer — Small v1 · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_small_unwa.ckpt`
- **Config:** `mbr_small_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_small_unwa_config.yaml

### MelBand Roformer — SpeechSep · AliceN

- **Source:** mvsepless
- **Weight:** `mbr_speech_alicen.ckpt`
- **Config:** `mbr_speech_alicen_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** two_stem
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Best result:** Multi-stem: vocals, other
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_speech_alicen_config.yaml

### MelBand Roformer — Super Big DeReverb · Sucial

- **Source:** mvsepless
- **Weight:** `mbr_desuperbigreverb_sucial.ckpt`
- **Config:** `mbr_desuperbigreverb_sucial_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:mbr_desuperbigreverb_sucial_config.yaml

### MelBand Roformer — Toon · jazzpear

- **Source:** mvsepless
- **Weight:** `mbr_toon_jazzpear.ckpt`
- **Config:** `mbr_toon_jazzpear_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** single_target:anime
- **Primary stem (backend):** `anime`
- **Instruments:** anime, other
- **Target instrument:** `anime`
- **Best result:** anime (single native output)
- **Metadata:** bundled_yaml:mbr_toon_jazzpear_config.yaml

### MelBand Roformer — Vocals Big Beta v5e · Unwa

- **Source:** mvsepless
- **Weight:** `mbr_bigbeta5e_unwa.ckpt`
- **Config:** `mbr_bigbeta5e_unwa_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_bigbeta5e_unwa_config.yaml

### MelBand Roformer — Vocals Fv1 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv1_gabox.ckpt`
- **Config:** `mbr_vocalsfv1_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv1_gabox_config.yaml

### MelBand Roformer — Vocals Fv2 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv2_gabox.ckpt`
- **Config:** `mbr_vocalsfv2_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv2_gabox_config.yaml

### MelBand Roformer — Vocals Fv3 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv3_gabox.ckpt`
- **Config:** `mbr_vocalsfv3_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv3_gabox_config.yaml

### MelBand Roformer — Vocals Fv4 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv4_gabox.ckpt`
- **Config:** `mbr_vocalsfv4_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv4_gabox_config.yaml

### MelBand Roformer — Vocals Fv5 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv5_gabox.ckpt`
- **Config:** `mbr_vocalsfv5_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv5_gabox_config.yaml

### MelBand Roformer — Vocals Fv6 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv6_gabox.ckpt`
- **Config:** `mbr_vocalsfv6_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv6_gabox_config.yaml

### MelBand Roformer — Vocals Fv7 Beta 1 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv7_beta1_gabox.ckpt`
- **Config:** `mbr_vocalsfv7_beta1_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv7_beta1_gabox_config.yaml

### MelBand Roformer — Vocals Fv7 Beta 2 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv7_beta2_gabox.ckpt`
- **Config:** `mbr_vocalsfv7_beta2_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv7_beta2_gabox_config.yaml

### MelBand Roformer — Vocals Fv7 Beta 3 · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv7_beta3_gabox.ckpt`
- **Config:** `mbr_vocalsfv7_beta3_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv7_beta3_gabox_config.yaml

### MelBand Roformer — Vocals Fv7 Final · GaboxR67

- **Source:** mvsepless
- **Weight:** `mbr_vocalsfv7_gabox.ckpt`
- **Config:** `mbr_vocalsfv7_gabox_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_vocalsfv7_gabox_config.yaml

### MelBand Roformer — Vocals · ViperX

- **Source:** mvsepless
- **Weight:** `mbr_vocals_viperx.ckpt`
- **Config:** `mbr_vocals_viperx_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_vocals_viperx_config.yaml

### MelBand Roformer — Vocals · ZFTurbo

- **Source:** mvsepless
- **Weight:** `mbr_vocals_zfturbo.ckpt`
- **Config:** `mbr_vocals_zfturbo_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:mbr_vocals_zfturbo_config.yaml

### MelBand Roformer — Xeno · DrYound3r

- **Source:** mvsepless
- **Weight:** `mbr_xeno.ckpt`
- **Config:** `mbr_xeno_config.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrum
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:mbr_xeno_config.yaml

## Roformer (detail)

### BandSplit Roformer — Drum/Bass Separation (SDR 10.53) · ViperX

- **Source:** TRvlvr
- **Weight:** `model_bs_roformer_ep_937_sdr_10.5309.ckpt`
- **Name intent:** drum_bass_sep
- **Backend focus:** special_fx_primary:no drum-bass
- **Primary stem (backend):** `no drum-bass`
- **Best result:** no drum-bass (drum/bass separation; complement = Drum-Bass)
- **Save stems UI:** UI: No Drum-Bass / Drum-Bass subset
- **Metadata:** community_models.txt
- **Note:** Community ref: no drum-bass*, drum-bass

### BandSplit Roformer — ViperX 12.96

- **Source:** TRvlvr
- **Weight:** `model_bs_roformer_ep_368_sdr_12.9628.ckpt`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (12.1), instrumental (16.3)

### BandSplit Roformer — ViperX 12.97

- **Source:** TRvlvr
- **Weight:** `model_bs_roformer_ep_317_sdr_12.9755.ckpt`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (11.8), instrumental (16.5)

### BandSplit Roformer — Fine-Tuned (4 Stems) · SYH99999

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
- **Metadata:** bundled_yaml:config_BandSplit_Roformer_4stems_FT_by_SYH99999.yaml

### BandSplit Roformer — Chorus Male/Female · Sucial

- **Source:** Politrees
- **Weight:** `model_chorus_bs_roformer_ep_267_sdr_24.1275.ckpt`
- **Config:** `config_bs_roformer_chorus_male_female.yaml`
- **Architecture:** BS Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_two_stem
- **Primary stem (backend):** `male`
- **Instruments:** male, female
- **Best result:** male, female
- **Save stems UI:** UI: male / female subset
- **Metadata:** bundled_yaml:config_bs_roformer_chorus_male_female.yaml
- **Note:** Community ref: male, female

### BandSplit Roformer — DeReverb · Anvuew

- **Source:** Politrees
- **Weight:** `deverb_bs_roformer_8_384dim_10depth.ckpt`
- **Config:** `config_bs_roformer_deverb_8_384dim_10depth.yaml`
- **Architecture:** BS Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:config_bs_roformer_deverb_8_384dim_10depth.yaml
- **Note:** Community ref: noreverb*, reverb

### BandSplit Roformer — FNO · Unwa

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
- **Metadata:** bundled_yaml:config_BandSplit-Roformer_FNO_by-Unwa.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — HyperACE Instrumental · Unwa

- **Source:** extras
- **Weight:** `bs_hyperace.ckpt`
- **Config:** `config_bs_hyperace.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** single_target:instrument
- **Primary stem (backend):** `instrument`
- **Instruments:** vocals, instrument
- **Target instrument:** `instrument`
- **Best result:** instrument (single native output)
- **Metadata:** bundled_yaml:config_bs_hyperace.yaml

### BandSplit Roformer — HyperACE v2 Instrumental · Unwa

- **Source:** extras
- **Weight:** `bs_roformer_inst_hyperacev2.ckpt`
- **Config:** `config_bs_hyperace_v2_inst.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** single_target:instrument
- **Primary stem (backend):** `instrument`
- **Instruments:** vocals, instrument
- **Target instrument:** `instrument`
- **Best result:** instrument (single native output)
- **Metadata:** bundled_yaml:config_bs_hyperace_v2_inst.yaml

### BandSplit Roformer — HyperACE v2 Vocals · Unwa

- **Source:** extras
- **Weight:** `bs_roformer_voc_hyperacev2.ckpt`
- **Config:** `config_bs_hyperace_v2_voc.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instrument
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_bs_hyperace_v2_voc.yaml

### BandSplit Roformer — Instrumental EXP Value Residual · Unwa [BS_Inst_EXP_VRL]

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
- **Metadata:** bundled_yaml:config_bs_roformer_inst_exp_vrl.yaml

### BandSplit Roformer — Karaoke Frazer · Becruily

- **Source:** Politrees
- **Weight:** `model_BandSplit-Roformer_Karaoke_Frazer_by-becruily.ckpt`
- **Config:** `config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml

### BandSplit Roformer — Male/Female · Aufr33

- **Source:** Politrees
- **Weight:** `bs_roformer_male_female_by_aufr33_sdr_7.2889.ckpt`
- **Config:** `config_bs_roformer_chorus_male_female.yaml`
- **Architecture:** BS Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_two_stem
- **Primary stem (backend):** `male`
- **Instruments:** male, female
- **Best result:** male, female
- **Save stems UI:** UI: male / female subset
- **Metadata:** bundled_yaml:config_bs_roformer_chorus_male_female.yaml

### BandSplit Roformer — Resurrection Instrumental · Unwa

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
- **Metadata:** bundled_yaml:config_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer — Resurrection Vocals · Unwa

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
- **Metadata:** bundled_yaml:config_BandSplit-Roformer_Resurrection_Vocals_by-Unwa.yaml

### BandSplit Roformer — Revive · Unwa

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
- **Metadata:** bundled_yaml:config_bs_roformer_revive_by_unwa.yaml

### BandSplit Roformer — Revive v2 · Unwa

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
- **Metadata:** bundled_yaml:config_bs_roformer_revive_by_unwa.yaml

### BandSplit Roformer — Revive v3 · Unwa

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
- **Metadata:** bundled_yaml:config_bs_roformer_revive_by_unwa.yaml

### BandSplit Roformer — SW · Jarredou

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
- **Metadata:** bundled_yaml:config_BandSplit-Roformer_SW_by-jarredou.yaml
- **Note:** Intent inferred from metadata (multi_stem)

### BandSplit Roformer — Vocals · Gabox

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

### MelBand Roformer — Vocals (SDR 11.44) · ViperX

- **Source:** TRvlvr
- **Weight:** `model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.5), instrumental (15.1)

### MelBand Roformer — Kim Big Beta v4 Fine-Tuned · Unwa

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
- **Metadata:** bundled_yaml:config_melband_roformer_big_beta4.yaml
- **Note:** Community ref: vocals* (12.5), other

### MelBand Roformer — Kim Big Beta v5e Fine-Tuned · Unwa

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
- **Metadata:** bundled_yaml:config_melband_roformer_big_beta5e.yaml
- **Note:** Community ref: vocals* (12.4), other

### MelBand Roformer — Kim Big Beta v6 Fine-Tuned · Unwa

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
- **Metadata:** bundled_yaml:config_melband_roformer_big_beta6.yaml

### MelBand Roformer — Kim Big Beta v6x Fine-Tuned · Unwa

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
- **Metadata:** bundled_yaml:config_melband_roformer_big_beta6x.yaml

### MelBand Roformer — Kim Big SYHFT v1 · SYH99999

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_big_v1_ft.yaml
- **Note:** Community ref: vocals* (12.3), other

### MelBand Roformer — Kim Fine-Tuned · Unwa

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

### MelBand Roformer — Kim Fine-Tuned v2 Bleedless · Unwa

- **Source:** Politrees
- **Weight:** `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt`
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

### MelBand Roformer — Kim Fine-Tuned v2 · Unwa

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

### MelBand Roformer — Kim Instrumental v1 · Unwa

- **Source:** TRvlvr
- **Weight:** `melband_roformer_inst_v1.ckpt`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.9), vocals (9.8)

### MelBand Roformer — Kim Instrumental v2 · Unwa

- **Source:** TRvlvr
- **Weight:** `melband_roformer_inst_v2.ckpt`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (16.1), vocals (10.3)

### MelBand Roformer — Kim Instrumental v1e Plus · Unwa

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

### MelBand Roformer — Kim Instrumental v1e · Unwa

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

### MelBand Roformer — Kim Instrumental/Vocals Duality v1 · Unwa

- **Source:** TRvlvr
- **Weight:** `melband_roformer_instvoc_duality_v1.ckpt`
- **Name intent:** dual_voc_inst
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals (11.0), instrumental (16.1)

### MelBand Roformer — Kim Instrumental/Vocals Duality v2 · Unwa

- **Source:** TRvlvr
- **Weight:** `melband_roformer_instvox_duality_v2.ckpt`
- **Name intent:** dual_voc_inst
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals (11.0), instrumental (16.1)

### MelBand Roformer — Kim SYHFT · SYH99999

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (8.0), other

### MelBand Roformer — Kim SYHFT v2 · SYH99999

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (8.6), other

### MelBand Roformer — Kim SYHFT v2.5 · SYH99999

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (8.5), other

### MelBand Roformer — Kim SYHFT v3 · SYH99999

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (9.5), other

### MelBand Roformer — Kim Vocals Fullness v1 · Aname

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer — Kim Vocals Fullness v2 · Aname

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer — Kim Vocals v1 · Aname

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer — Kim Vocals v2 · Aname

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer — Kim Vocals v3 · Aname

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer — Fine-Tuned Large v1 (4 Stems) · SYH99999

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
- **Metadata:** bundled_yaml:config_MelBand_Roformer_4stems_FT_Large_by_SYH99999.yaml

### MelBand Roformer — Fine-Tuned Large v2 (4 Stems) · SYH99999

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
- **Metadata:** bundled_yaml:config_MelBand_Roformer_4stems_FT_Large_by_SYH99999.yaml

### MelBand Roformer — Large v1 (4 Stems) · Aname

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
- **Metadata:** bundled_yaml:config_MelBand_Roformer_4stems_Large_v1_by_Aname.yaml

### MelBand Roformer — XL v1 (4 Stems) · Aname

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
- **Metadata:** bundled_yaml:config_MelBand_Roformer_4stems_XL_v1_by_Aname.yaml

### MelBand Roformer — Aspiration Less Aggressive · Sucial

- **Source:** Politrees
- **Weight:** `aspiration_mel_band_roformer_less_aggr_sdr_18.1201.ckpt`
- **Config:** `config_melband_roformer_aspiration.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_two_stem
- **Primary stem (backend):** `aspiration`
- **Instruments:** aspiration, other
- **Best result:** aspiration, other
- **Save stems UI:** UI: aspiration / other subset
- **Metadata:** bundled_yaml:config_melband_roformer_aspiration.yaml
- **Note:** Community ref: aspiration, other

### MelBand Roformer — Aspiration · Sucial

- **Source:** Politrees
- **Weight:** `aspiration_mel_band_roformer_sdr_18.9845.ckpt`
- **Config:** `config_melband_roformer_aspiration.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_two_stem
- **Primary stem (backend):** `aspiration`
- **Instruments:** aspiration, other
- **Best result:** aspiration, other
- **Save stems UI:** UI: aspiration / other subset
- **Metadata:** bundled_yaml:config_melband_roformer_aspiration.yaml
- **Note:** Community ref: aspiration, other

### MelBand Roformer — Karaoke BVE · Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_BVE_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_BVE_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:Lead
- **Primary stem (backend):** `Lead`
- **Instruments:** Lead, Back
- **Target instrument:** `Lead`
- **Best result:** Lead, Back
- **Save stems UI:** UI: Lead / Back subset
- **Metadata:** bundled_yaml:config_MelBand-Roformer_BVE_by-Gonza.yaml

### MelBand Roformer — Bleed Suppressor v1 · Unwa & 97chris

- **Source:** Politrees
- **Weight:** `mel_band_roformer_bleed_suppressor_v1.ckpt`
- **Config:** `config_melband_roformer_bleed_suppressor_v1.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Bleed
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:config_melband_roformer_bleed_suppressor_v1.yaml
- **Note:** Community ref: instrumental*, bleed

### MelBand Roformer — Crowd · Aufr33 & ViperX

- **Source:** Politrees
- **Weight:** `mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt`
- **Config:** `config_melband_roformer_crowd_aufr33_viperx_sdr_8.7144.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:crowd
- **Primary stem (backend):** `crowd`
- **Instruments:** crowd, other
- **Target instrument:** `crowd`
- **Best result:** crowd, other
- **Save stems UI:** UI: crowd / other subset
- **Metadata:** bundled_yaml:config_melband_roformer_crowd_aufr33_viperx_sdr_8.7144.yaml
- **Note:** Community ref: crowd*, other

### MelBand Roformer — DeReverb Big · Sucial

- **Source:** Politrees
- **Weight:** `dereverb_big_mbr_ep_362.ckpt`
- **Config:** `config_melband_roformer_dereverb_echo_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb_echo_v2.yaml

### MelBand Roformer — DeReverb Less Aggressive · Anvuew

- **Source:** Politrees
- **Weight:** `dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt`
- **Config:** `config_melband_roformer_dereverb_anvuew.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb_anvuew.yaml
- **Note:** Community ref: noreverb*, reverb

### MelBand Roformer — DeReverb Mono · Anvuew

- **Source:** Politrees
- **Weight:** `dereverb_mel_band_roformer_mono_anvuew_sdr_20.4029.ckpt`
- **Config:** `config_melband_roformer_dereverb_anvuew.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb_anvuew.yaml

### MelBand Roformer — DeReverb Super Big · Sucial

- **Source:** Politrees
- **Weight:** `dereverb_super_big_mbr_ep_346.ckpt`
- **Config:** `config_melband_roformer_dereverb_echo_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb_echo_v2.yaml

### MelBand Roformer — DeReverb · Anvuew

- **Source:** Politrees
- **Weight:** `dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt`
- **Config:** `config_melband_roformer_dereverb_anvuew.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** No reverb (dereverbbed signal)
- **Save stems UI:** UI: noreverb / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb_anvuew.yaml
- **Note:** Community ref: noreverb*, reverb

### MelBand Roformer — DeReverb-Echo Fused · Sucial

- **Source:** Politrees
- **Weight:** `dereverb_echo_mbr_fused.ckpt`
- **Config:** `config_melband_roformer_dereverb_echo_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb_echo_v2.yaml

### MelBand Roformer — DeReverb-Echo · Sucial

- **Source:** Politrees
- **Weight:** `dereverb-echo_mel_band_roformer_sdr_10.0169.ckpt`
- **Config:** `config_melband_roformer_dereverb-echo.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `dry`
- **Instruments:** dry, No dry
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb-echo.yaml
- **Note:** Community ref: dry, no dry

### MelBand Roformer — DeReverb-Echo v2 · Sucial

- **Source:** Politrees
- **Weight:** `dereverb-echo_mel_band_roformer_sdr_13.4843_v2.ckpt`
- **Config:** `config_melband_roformer_dereverb-echo_sdr_13.4843_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, No dry
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_dereverb-echo_sdr_13.4843_v2.yaml
- **Note:** Community ref: dry*, no dry

### MelBand Roformer — DeNoise Aggr · Aufr33

- **Source:** Politrees
- **Weight:** `denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt`
- **Config:** `config_melband_roformer_denoise_aufr33_aggr_sdr_27.9768.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_denoise_aufr33_aggr_sdr_27.9768.yaml
- **Note:** Community ref: dry*, other

### MelBand Roformer — DeNoise · Aufr33

- **Source:** Politrees
- **Weight:** `denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt`
- **Config:** `config_melband_roformer_denoise_aufr33_sdr_27.9959.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** special_fx_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** Dry (dereverbbed signal)
- **Save stems UI:** UI: dry / complement stem
- **Metadata:** bundled_yaml:config_melband_roformer_denoise_aufr33_sdr_27.9959.yaml
- **Note:** Community ref: dry*, other

### MelBand Roformer — Duality v1 · Aname

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
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Duality_v1_by-Aname.yaml

### MelBand Roformer — Guitar · Becruily

- **Source:** Politrees
- **Weight:** `melband_roformer_guitar_becruily.ckpt`
- **Config:** `config_melband_roformer_guitar_becruily.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** specialty_stem
- **Backend focus:** specialty_target:Guitar
- **Primary stem (backend):** `Guitar`
- **Instruments:** Guitar, Other
- **Target instrument:** `Guitar`
- **Best result:** Guitar, Other
- **Save stems UI:** UI: Guitar / Other subset
- **Metadata:** bundled_yaml:config_melband_roformer_guitar_becruily.yaml

### MelBand Roformer — Instrumental Bleedless v1 · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_bleedless_v1_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Bleedless v2 · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_bleedless_v2_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental DeNoise-DeBleed · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_denoise_debleed_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v1 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v2 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v3 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v4 Noise · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v4_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v5 Noise · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v5_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v5 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v6 Noise · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v6_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v6 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v7 Noise · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v7_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v7 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness v8 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental Fullness vX · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental · Becruily

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
- **Metadata:** bundled_yaml:config_melband_roformer_instrumental_becruily.yaml

### MelBand Roformer — Instrumental v1 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental v2 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Instrumental v3 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer — Karaoke Fusion Aggressive · Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Aggressive_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml

### MelBand Roformer — Karaoke Fusion Aggressive v2 · Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Aggressive_v2_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_v2_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Karaoke_Fusion_v2_by-Gonza.yaml

### MelBand Roformer — Karaoke Fusion Standard · Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Standard_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml

### MelBand Roformer — Karaoke Fusion Total · Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Total_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_Total_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Karaoke_Fusion_Total_by-Gonza.yaml

### MelBand Roformer — Karaoke · Aufr33 & ViperX

- **Source:** Politrees
- **Weight:** `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`
- **Config:** `config_melband_roformer_karaoke_aufr33_viperx_sdr_10.1956.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_melband_roformer_karaoke_aufr33_viperx_sdr_10.1956.yaml
- **Note:** Community ref: vocals* (8.4), instrumental (14.7)

### MelBand Roformer — Karaoke · Gabox

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_by-Gabox.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_by-Gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Karaoke_by-Gabox.yaml

### MelBand Roformer — Karaoke Beta · Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_karaoke_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Karaoke · Becruily

- **Source:** Politrees
- **Weight:** `melband_roformer_karaoke_becruily.ckpt`
- **Config:** `config_melband_roformer_karaoke_becruily.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** bundled_yaml:config_melband_roformer_karaoke_becruily.yaml

### MelBand Roformer — Small · Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_small_by_aname.ckpt`
- **Config:** `config_melband_roformer_small_by_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocal_pair
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** bundled_yaml:config_melband_roformer_small_by_aname.yaml

### MelBand Roformer — Vocals Fullness · Aname

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer — Vocals Fullness v1 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Vocals Fullness v2 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Vocals Fullness v3 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Vocals Fullness v4 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Vocals Fullness v5 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Vocals Fullness v6 · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Vocals · Gabox

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
- **Metadata:** bundled_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer — Vocals · Kimberley Jensen

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_kim.yaml
- **Note:** Community ref: vocals* (12.6), other

### MelBand Roformer — Vocals · Becruily

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
- **Metadata:** bundled_yaml:config_melband_roformer_vocals_becruily.yaml

### MelBand Roformer — Instrumental Metal Preview · Mesk

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
- **Metadata:** bundled_yaml:config_melband_roformer_inst_metal_prev_by_mesk.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

## MDX-Net (detail)

### SCNet — Huge v1 (4 Stems) · Aname

- **Source:** mvsepless
- **Weight:** `scnet_huge_4stem_aname.ckpt`
- **Config:** `scnet_huge_4stem_aname_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_huge_4stem_aname_config.yaml

### SCNet — XL (4 Stems) · StarryTong

- **Source:** mvsepless
- **Weight:** `scnet_xl_4stem_starrytong.ckpt`
- **Config:** `scnet_xl_4stem_starrytong_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_xl_4stem_starrytong_config.yaml

### SCNet — XL (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `scnet_xl_4stem_zftrubo.ckpt`
- **Config:** `scnet_xl_4stem_zftrubo_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_xl_4stem_zftrubo_config.yaml

### SCNet (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `scnet_4stem_zfturbo.ckpt`
- **Config:** `scnet_4stem_zfturbo_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_4stem_zfturbo_config.yaml

### SCNet — ChoirSep · Dry Paint Dealer Undr

- **Source:** mvsepless
- **Weight:** `scnet_choirsep_exp.ckpt`
- **Config:** `scnet_choirsep_exp_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `alto`
- **Instruments:** alto, bass, soprano, tenor
- **Best result:** Multi-stem: alto, bass, soprano, tenor
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_choirsep_exp_config.yaml

### SCNet — Large Jazz model · Joris Vaneyghen

- **Source:** mvsepless
- **Weight:** `scnet_jazz_4stem_jorisvaneyghen.ckpt`
- **Config:** `scnet_jazz_4stem_jorisvaneyghen_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, piano, other
- **Best result:** Multi-stem: drums, bass, piano, other
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_jazz_4stem_jorisvaneyghen_config.yaml

### SCNet — Masked Small (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `scnet_masked_small_4stem_zftrubo.ckpt`
- **Config:** `scnet_masked_small_4stem_zftrubo_config.yaml`
- **Architecture:** SCNet Masked
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_masked_small_4stem_zftrubo_config.yaml

### SCNet — Masked XL IHF (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `scnet_masked_xl_ihf_4stem_zftrubo.ckpt`
- **Config:** `scnet_masked_xl_ihf_4stem_zftrubo_config.yaml`
- **Architecture:** SCNet Masked
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_masked_xl_ihf_4stem_zftrubo_config.yaml

### SCNet — Masked ChoirSep · Dry Paint Dealer Undr

- **Source:** mvsepless
- **Weight:** `scnet_masked_choirsep_exp.ckpt`
- **Config:** `scnet_masked_choirsep_exp_config.yaml`
- **Architecture:** SCNet Masked
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `soprano`
- **Instruments:** soprano, alto, tenor, bass
- **Best result:** Multi-stem: soprano, alto, tenor, bass
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_masked_choirsep_exp_config.yaml

### SCNet — Mid-Side v2 · Gilliaaan

- **Source:** mvsepless
- **Weight:** `scnet_mid_side2_gilliaaan.ckpt`
- **Config:** `scnet_mid_side2_gilliaaan_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** two_stem
- **Primary stem (backend):** `center`
- **Instruments:** center, wide
- **Best result:** Multi-stem: center, wide
- **Metadata:** bundled_yaml:scnet_mid_side2_gilliaaan_config.yaml

### SCNet — Surround · Jasper

- **Source:** mvsepless
- **Weight:** `scnet_surround_jasper.ckpt`
- **Config:** `scnet_surround_jasper_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `LRF`
- **Instruments:** LRF, LFE, LRS, CEN
- **Best result:** Multi-stem: LRF, LFE, LRS, CEN
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_surround_jasper_config.yaml

### SCNet — Tran (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `scnet_tran_4stem_zftrubo.ckpt`
- **Config:** `scnet_tran_4stem_zftrubo_config.yaml`
- **Architecture:** SCNet Tran
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_tran_4stem_zftrubo_config.yaml

### SCNet — XL IHF (4 Stems) · ZFTurbo

- **Source:** mvsepless
- **Weight:** `scnet_xl_ihf_4stem_zfturbo.ckpt`
- **Config:** `scnet_xl_ihf_4stem_zfturbo_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_xl_ihf_4stem_zfturbo_config.yaml

### SCNet — XL Jazz model · Joris Vaneyghen

- **Source:** mvsepless
- **Weight:** `scnet_xl_jazz_4stem_jorisvaneyghen.ckpt`
- **Config:** `scnet_xl_jazz_4stem_jorisvaneyghen_config.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, piano, other
- **Best result:** Multi-stem: drums, bass, piano, other
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:scnet_xl_jazz_4stem_jorisvaneyghen_config.yaml

## SCNet (detail)

### SCNet — Huge Bleedless (4 Stems) · Aname

- **Source:** extras
- **Weight:** `huge_scnet_4stems_bleedless.ckpt`
- **Config:** `config_huge_scnet_4stems.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_huge_scnet_4stems.yaml

### SCNet — Huge Fullness (4 Stems) · Aname

- **Source:** extras
- **Weight:** `huge_scnet_4stems_fullness.ckpt`
- **Config:** `config_huge_scnet_4stems.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_huge_scnet_4stems.yaml

### SCNet — Huge Strong Fullness (4 Stems) · Aname

- **Source:** extras
- **Weight:** `huge_scnet_4stems_strong_fullness.ckpt`
- **Config:** `config_huge_scnet_4stems.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_huge_scnet_4stems.yaml

### SCNet — Huge v1.2 (4 Stems) · Aname

- **Source:** extras
- **Weight:** `huge_scnet_4stems_v1.2.ckpt`
- **Config:** `config_huge_scnet_4stems.yaml`
- **Architecture:** SCNet
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_huge_scnet_4stems.yaml

### SCNet — Large (4 Stems)

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

### SCNet — Large (4 Stems) · StarryTong

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

### SCNet — MUSDB18 (4 Stems) · StarryTong

- **Source:** Politrees
- **Weight:** `scnet_checkpoint_musdb18.ckpt`
- **Config:** `config_musdb18_scnet.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `Drums`
- **Instruments:** Drums, Bass, Other, Vocals
- **Best result:** Multi-stem: Drums, Bass, Other, Vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_musdb18_scnet.yaml

### SCNet — XL (4 Stems)

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

### Demucs v1 — Time-Domain

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v1 — Time-Domain Extra

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs_extra.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v1 — Light

- **Source:** TRvlvr+Politrees
- **Weight:** `light.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v1 — Light Extra

- **Source:** TRvlvr+Politrees
- **Weight:** `light_extra.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v1 — Conv-TasNet

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v1 — Conv-TasNet Extra

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet_extra.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v2 — Time-Domain

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs-e07c671f.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v2 — Time-Domain 48 kHz HQ

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs48_hq-28a1282c.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v2 — Time-Domain Extra

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs_extra-3646af93.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v2 — Unit Test

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs_unittest-09ebc15f.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v2 — Conv-TasNet

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet-beb46fac.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v2 — Conv-TasNet Extra

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet_extra-df3777b2.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v3 — UVR Model (2 Stems)

- **Source:** TRvlvr+Politrees
- **Weight:** `ebf34a2db.th`
- **Config:** `UVR_Demucs_Model_1.yaml`
- **Architecture:** MDX23C
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Instruments:** instrumental, vocals
- **Best result:** 2-stem: instrumental + vocals (user picks focus)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** demucs_heuristic

### Demucs v3 — MDX

- **Source:** TRvlvr+Politrees
- **Weight:** `c511e2ab-fe698775.th`
- **Config:** `mdx.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v3 — MDX Extra

- **Source:** TRvlvr+Politrees
- **Weight:** `e51eebcc-c1b80bdd.th`
- **Config:** `mdx_extra.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v3 — MDX Extra Quantized

- **Source:** TRvlvr+Politrees
- **Weight:** `83fc094f-4a16d450.th`
- **Config:** `mdx_extra_q.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v3 — MDX Quantized

- **Source:** TRvlvr+Politrees
- **Weight:** `b72baf4e-8778635e.th`
- **Config:** `mdx_q.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v3 — Repro MDX A

- **Source:** TRvlvr+Politrees
- **Weight:** `fa0cb7f9-100d8bf4.th`
- **Config:** `repro_mdx_a.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v3 — Repro MDX A Hybrid Only

- **Source:** TRvlvr+Politrees
- **Weight:** `fa0cb7f9-100d8bf4.th`
- **Config:** `repro_mdx_a_hybrid_only.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v3 — Repro MDX A Time-Domain Only

- **Source:** TRvlvr+Politrees
- **Weight:** `9a6b4851-03af0aa6.th`
- **Config:** `repro_mdx_a_time_only.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v4 — Hybrid Demucs MMI

- **Source:** TRvlvr+Politrees
- **Weight:** `75fc33f5-1941ce65.th`
- **Config:** `hdemucs_mmi.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v4 — Hybrid Transformer

- **Source:** TRvlvr+Politrees
- **Weight:** `955717e8-8726e21a.th`
- **Config:** `htdemucs.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v4 — Hybrid Transformer (6 Stems)

- **Source:** TRvlvr+Politrees
- **Weight:** `5c90dfd2-34c22ccb.th`
- **Config:** `htdemucs_6s.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals, guitar, piano
- **Best result:** 6-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

### Demucs v4 — Hybrid Transformer Fine-Tuned

- **Source:** TRvlvr+Politrees
- **Weight:** `f7e0c4bc-ba3fe64a.th`
- **Config:** `htdemucs_ft.yaml`
- **Architecture:** MDX23C
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** demucs_heuristic

## Apollo (detail)

### Apollo — EDM Restoration Big · Essid

- **Source:** extras
- **Weight:** `apollo_edm_big_by_essid.ckpt`
- **Config:** `apollo_edm_big_by_essid.yaml`
- **Name intent:** unknown
- **Backend focus:** unknown
- **Best result:** unknown
- **Metadata:** unavailable

### Apollo — EDM Restoration · Essid

- **Source:** extras
- **Weight:** `apollo_edm_by_essid.ckpt`
- **Config:** `apollo_edm_by_essid.yaml`
- **Name intent:** unknown
- **Backend focus:** unknown
- **Best result:** unknown
- **Metadata:** unavailable
