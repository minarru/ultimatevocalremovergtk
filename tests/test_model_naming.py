"""Canonical display names across the four catalogue label dialects."""

import unittest

from core.model_naming import (
    canonical_display_name,
    project_model_display,
    strip_catalogue_prefix,
)


class StripCataloguePrefixTests(unittest.TestCase):
    def test_strips_download_center_category_prefixes(self) -> None:
        self.assertEqual(
            strip_catalogue_prefix("Roformer Model: BandSplit Roformer | HyperACE v2 by Unwa"),
            "BandSplit Roformer | HyperACE v2 by Unwa",
        )
        self.assertEqual(strip_catalogue_prefix("MDX23C Model VIP: Foo"), "Foo")
        self.assertEqual(strip_catalogue_prefix("MDX23 Model: Legacy"), "Legacy")
        self.assertEqual(
            strip_catalogue_prefix("SCnet: 4-stems Huge by Aname"), "4-stems Huge by Aname"
        )

    def test_strips_vr_prefixes(self) -> None:
        self.assertEqual(strip_catalogue_prefix("VR Arch Single Model v5: 1_HP-UVR"), "1_HP-UVR")

    def test_leaves_unprefixed_label_alone(self) -> None:
        self.assertEqual(strip_catalogue_prefix("MDX23C InstVoc HQ"), "MDX23C InstVoc HQ")

    def test_strips_trailing_ckpt_extension(self) -> None:
        self.assertEqual(strip_catalogue_prefix("Some Model.ckpt"), "Some Model")


class CanonicalDisplayNameTests(unittest.TestCase):
    def test_four_dialects_converge(self) -> None:
        cases = {
            "MDX23C InstVoc HQ": "MDX23C — InstVoc HQ",
            "MelBand Roformer | Karaoke by Aufr33 & Viperx": "MelBand Roformer — Karaoke · Aufr33 & Viperx",
            "Roformer Model: BandSplit Roformer | HyperACE v2 Instrumental by Unwa": "BandSplit Roformer — HyperACE v2 Instrumental · Unwa",
            "Mel-Band Roformer Vocals by Kimberley Jensen": "MelBand Roformer — Vocals · Kimberley Jensen",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonical_display_name(raw), expected)

    def test_family_spellings_unify(self) -> None:
        for raw in ("Mel-Band Roformer Foo", "mel_band_roformer Foo", "MelBand Roformer Foo"):
            with self.subTest(raw=raw):
                self.assertTrue(canonical_display_name(raw).startswith("MelBand Roformer — "))
        for raw in ("BS-Roformer Foo", "BS Roformer Foo", "BandSplit Roformer Foo"):
            with self.subTest(raw=raw):
                self.assertTrue(canonical_display_name(raw).startswith("BandSplit Roformer — "))

    def test_descriptive_middle_is_verbatim(self) -> None:
        self.assertEqual(
            canonical_display_name("MelBand Roformer | Inst Fullness v8 (experimental) by Gabox"),
            "MelBand Roformer — Inst Fullness v8 (experimental) · Gabox",
        )

    def test_crops_hyperace_finetune_parenthetical(self) -> None:
        self.assertEqual(
            canonical_display_name(
                "BS Roformer Instrumental HyperACE v2 (finetuned anvuew vocal model) by Unwa"
            ),
            "BandSplit Roformer — Instrumental HyperACE v2 · Unwa",
        )
        # Idempotent on the already-cropped (and already-canonical) form.
        cropped = "BandSplit Roformer — Instrumental HyperACE v2 · Unwa"
        self.assertEqual(canonical_display_name(cropped), cropped)

    def test_label_without_family_passes_through(self) -> None:
        self.assertEqual(canonical_display_name("UVR-DeNoise-Lite"), "UVR-DeNoise-Lite")

    def test_label_without_author_has_no_separator(self) -> None:
        self.assertEqual(canonical_display_name("MDX23C InstVoc HQ 2"), "MDX23C — InstVoc HQ 2")

    def test_empty_input_is_safe(self) -> None:
        self.assertEqual(canonical_display_name(""), "")

    def test_prefix_supplies_the_family_when_the_remainder_does_not(self) -> None:
        # 'SCnet: ' is the only place the family is named — the remainder
        # starts with '4-stems'. Dropping the prefix would lose it.
        self.assertEqual(
            canonical_display_name("SCnet: 4-stems Huge SCNet Bleedless by Aname"),
            "SCNet — 4-stems Huge SCNet Bleedless · Aname",
        )
        self.assertEqual(
            canonical_display_name("MDX-Net Model: UVR-MDX-NET Inst HQ 4"),
            "MDX-Net — UVR-MDX-NET Inst HQ 4",
        )
        self.assertEqual(
            canonical_display_name("Apollo Model: EDM Restoration by essid"),
            "Apollo — EDM Restoration · essid",
        )
        self.assertEqual(
            canonical_display_name("MDX23 Model: MDX23C_D1581"),
            "MDX23C — D1581",
        )

    def test_remainder_family_beats_the_prefix(self) -> None:
        # 'Roformer Model: ' does not say which Roformer; the remainder does.
        self.assertEqual(
            canonical_display_name("Roformer Model: Mel-Band Roformer | Karaoke by Gabox"),
            "MelBand Roformer — Karaoke · Gabox",
        )

    def test_is_idempotent(self) -> None:
        for raw in (
            "Roformer Model: Mel-Band Roformer | Karaoke by Gabox",
            "SCnet: 4-stems Huge SCNet Bleedless by Aname",
            # Families canonical_family cannot re-detect are the hard cases:
            # without the already-canonical short-circuit these lose their
            # title separator on a second pass.
            "MDX-Net Model: UVR-MDX-NET Inst HQ 4",
            "Demucs v4: htdemucs_ft",
            "MDX23C InstVoc HQ",
            "UVR-DeNoise-Lite",
        ):
            with self.subTest(raw=raw):
                once = canonical_display_name(raw)
                self.assertEqual(canonical_display_name(once), once)


class ProjectModelDisplayTests(unittest.TestCase):
    def test_projector_applies_exact_aliases_before_source_formatting(self) -> None:
        """A curated alias must win only for its exact canonical ID."""
        self.assertEqual(
            project_model_display(
                "mdx:bs_pope_4stem_09072026_aname",
                source_label="BS PolarFormer 4 stems 09-07-2026 by Somebody Else",
            ),
            "BandSplit PolarFormer — 09-07-2026 (4 Stems) · Aname",
        )
        self.assertEqual(
            project_model_display("mdx:bs_pope_4stem_09072026_aname-copy"),
            "bs_pope_4stem_09072026_aname-copy",
        )

    def test_projector_precedence_and_conservative_source_formatting(self) -> None:
        """Trusted overrides win; unknown IDs format an exact label or remain raw."""
        self.assertEqual(
            project_model_display(
                "mdx:bs_pope_4stem_09072026_aname",
                explicit_display="Trusted title",
            ),
            "Trusted title",
        )
        self.assertEqual(
            project_model_display(
                "mdx:private-model",
                source_label="BS Roformer 4 stems FT InstVoc HQ by viperx",
            ),
            "BandSplit Roformer — Fine-Tuned Instrumental/Vocals HQ (4 Stems) · ViperX",
        )
        self.assertEqual(
            project_model_display("mdx:private-model"),
            "private-model",
        )

    def test_projector_curates_demucs_backend_from_an_exact_source_label(self) -> None:
        """Demucs generation remains visible when its artifact basename differs."""
        self.assertEqual(
            project_model_display(
                "demucs:htdemucs_ft-f7e0c4bc",
                source_label="Demucs v4: htdemucs_ft",
            ),
            "v4 — HTDemucs Fine-Tuned",
        )
        self.assertEqual(
            project_model_display(
                "demucs:demucs48_hq-28a1282c",
                source_label="Demucs v2: demucs48_hq",
            ),
            "v2 — Demucs 48 kHz HQ",
        )

    def test_projector_removes_a_repeated_family_after_the_stem_count(self) -> None:
        self.assertEqual(
            project_model_display(
                "mdx:huge_scnet_4stems_bleedless",
                source_label="SCnet: 4-stems Huge SCNet Bleedless by Aname",
            ),
            "SCNet — Huge Bleedless (4 Stems) · Aname",
        )

    def test_projector_normalizes_parenthetical_sdr_after_the_author(self) -> None:
        self.assertEqual(
            project_model_display(
                "mdx:mbr_inst_1652_essid",
                source_label="Mel-Band Roformer Instrumental by Essid (sdr 16.52)",
            ),
            "MelBand Roformer — Instrumental · Essid (SDR 16.52)",
        )

    def test_projector_uses_exact_aliases_for_reviewed_storage_copy(self) -> None:
        self.assertEqual(
            project_model_display(
                "mdx:kuielab_a_bass",
                source_label="MDX-Net Model: kuielab_a_bass",
            ),
            "MDX-Net — KUIELAB A Bass",
        )
        self.assertEqual(
            project_model_display(
                "mdx:bs_mega_53stem_bowed_strings_mvsep",
                source_label="BS Roformer Mega 53 stems (only Bowed_Strings) by MVSep",
            ),
            "BandSplit Roformer — Mega Bowed Strings Only (53 Stems) · MVSep",
        )

    def test_projector_uses_presentation_only_karaoke_wording_for_bve(self) -> None:
        self.assertEqual(
            project_model_display(
                "mdx:mbr_bve_gonzaluigi",
                source_label="Mel-Band Roformer BVE by Gonzaluigi",
            ),
            "MelBand Roformer — Karaoke BVE · Gonzaluigi",
        )

    def test_projector_normalizes_each_reviewed_author_component(self) -> None:
        self.assertEqual(
            project_model_display(
                "mdx:private-model",
                source_label="MelBand Roformer Karaoke by aufr33 & viperx",
            ),
            "MelBand Roformer — Karaoke · Aufr33 & ViperX",
        )
        self.assertEqual(
            project_model_display(
                "mdx:private-model",
                source_label="MDX23C DeReverb by aufr33 & jarredou",
            ),
            "MDX23C — DeReverb · Aufr33 & Jarredou",
        )
        self.assertEqual(
            project_model_display(
                "mdx:private-model",
                source_label="SCNet Large by chenCFD & neoculture",
            ),
            "SCNet — Large · chenCFD & neoculture",
        )

    def test_projector_normalizes_reviewed_compounds_pairs_and_states(self) -> None:
        cases = {
            "MelBand Roformer Denoise Debleed preview by Gabox": (
                "MelBand Roformer — DeNoise DeBleed Preview · Gabox"
            ),
            "BandSplit Roformer Male-Female final by aufr33": (
                "BandSplit Roformer — Male/Female Final · Aufr33"
            ),
            "SCNet Choirsep beta by starrytong": ("SCNet — ChoirSep Beta · StarryTong"),
        }
        for source_label, expected in cases.items():
            with self.subTest(source_label=source_label):
                self.assertEqual(
                    project_model_display("mdx:private-model", source_label=source_label),
                    expected,
                )

    def test_projector_places_stem_counts_after_complete_variants(self) -> None:
        cases = {
            "BS Roformer 4 stems by Aname": "BandSplit Roformer (4 Stems) · Aname",
            "MDX23C 4 Stems Small by KUIELAB": "MDX23C — Small (4 Stems) · KUIELAB",
            "Mel-Band Roformer 4 Stems v2 Large by Aname": (
                "MelBand Roformer — Large v2 (4 Stems) · Aname"
            ),
            "MelBand Roformer 4-stems FT Large v1 by SYH99999": (
                "MelBand Roformer — Fine-Tuned Large v1 (4 Stems) · SYH99999"
            ),
            "SCnet: 4-stems Huge SCNet Strong Fullness by Aname": (
                "SCNet — Huge Strong Fullness (4 Stems) · Aname"
            ),
        }
        for source_label, expected in cases.items():
            with self.subTest(source_label=source_label):
                self.assertEqual(
                    project_model_display("mdx:private-model", source_label=source_label),
                    expected,
                )

    def test_projector_uses_all_25_reviewed_stem_count_aliases(self) -> None:
        expected = {
            "mdx:bs_4stem_aname": "BandSplit Roformer (4 Stems) · Aname",
            "mdx:bs_4stem_zfturbo": "BandSplit Roformer (4 Stems) · ZFTurbo",
            "mdx:mdx23c_4stem_small_kuielab": "MDX23C — Small (4 Stems) · KUIELAB",
            "mdx:mdx23c_4stem_kuielab": "MDX23C (4 Stems) · KUIELAB",
            "mdx:mdx23c_4stem_zfturbo": "MDX23C (4 Stems) · ZFTurbo",
            "mdx:mbr_4stemlarge1_aname": "MelBand Roformer — Large (4 Stems) · Aname",
            "mdx:mbr_4stemlarge2_aname": "MelBand Roformer — Large v2 (4 Stems) · Aname",
            "mdx:mbr_4stemxl1_aname": "MelBand Roformer — XL (4 Stems) · Aname",
            "mdx:scnet_huge_4stem_aname": "SCNet — Huge v1 (4 Stems) · Aname",
            "mdx:scnet_xl_4stem_starrytong": "SCNet — XL (4 Stems) · StarryTong",
            "mdx:scnet_xl_4stem_zftrubo": "SCNet — XL (4 Stems) · ZFTurbo",
            "mdx:scnet_4stem_zfturbo": "SCNet (4 Stems) · ZFTurbo",
            "mdx:BandSplit_Roformer_4stems_FT_by_SYH99999": (
                "BandSplit Roformer — Fine-Tuned (4 Stems) · SYH99999"
            ),
            "mdx:MelBand_Roformer_4stems_FT_Large_v1_by_SYH99999": (
                "MelBand Roformer — Fine-Tuned Large v1 (4 Stems) · SYH99999"
            ),
            "mdx:MelBand_Roformer_4stems_FT_Large_v2_by_SYH99999": (
                "MelBand Roformer — Fine-Tuned Large v2 (4 Stems) · SYH99999"
            ),
            "mdx:MelBand_Roformer_4stems_Large_v1_by_Aname": (
                "MelBand Roformer — Large v1 (4 Stems) · Aname"
            ),
            "mdx:MelBand_Roformer_4stems_XL_v1_by_Aname": (
                "MelBand Roformer — XL v1 (4 Stems) · Aname"
            ),
            "mdx:huge_scnet_4stems_bleedless": (
                "SCNet — Huge Bleedless (4 Stems) · Aname"
            ),
            "mdx:huge_scnet_4stems_fullness": (
                "SCNet — Huge Fullness (4 Stems) · Aname"
            ),
            "mdx:huge_scnet_4stems_strong_fullness": (
                "SCNet — Huge Strong Fullness (4 Stems) · Aname"
            ),
            "mdx:huge_scnet_4stems_v1.2": "SCNet — Huge v1.2 (4 Stems) · Aname",
            "mdx:model_scnet_sdr_9.3244": "SCNet — Large (4 Stems)",
            "mdx:SCNet-large_starrytong_fixed": (
                "SCNet — Large (4 Stems) · StarryTong"
            ),
            "mdx:scnet_checkpoint_musdb18": (
                "SCNet — MUSDB18 (4 Stems) · StarryTong"
            ),
            "mdx:model_scnet_ep_54_sdr_9.8051": "SCNet — XL (4 Stems)",
        }
        self.assertEqual(len(expected), 25)
        for model_id, display in expected.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(project_model_display(model_id), display)

    def test_projector_preserves_hq_and_opaque_tokens(self) -> None:
        cases = {
            "MDX23C InstVoc HQ": "MDX23C — Instrumental/Vocals HQ",
            "MDX23C InstVoc High Quality": "MDX23C — Instrumental/Vocals HQ",
            "BandSplit Roformer FT Instrumental by Unwa": (
                "BandSplit Roformer — Fine-Tuned Instrumental · Unwa"
            ),
            "BandSplit Roformer SYHFT Instrumental by Unwa": (
                "BandSplit Roformer — SYHFT Instrumental · Unwa"
            ),
            "SCNet Fv9 SN MUSDB18 by jazzpear": "SCNet — Fv9 SN MUSDB18 · jazzpear",
        }
        for source_label, expected in cases.items():
            with self.subTest(source_label=source_label):
                actual = project_model_display("mdx:private-model", source_label=source_label)
                self.assertEqual(actual, expected)
                self.assertEqual(
                    project_model_display("mdx:private-model", source_label=actual),
                    actual,
                )

    def test_projector_uses_all_confirmed_exact_corrections(self) -> None:
        expected = {
            "mdx:bs_deverb_room_anvuew": "BandSplit Roformer — DeReverb Room · Anvuew",
            "mdx:bs_speech_alicen": "BandSplit Roformer — SpeechSep · AliceN",
            "mdx:bs_mag_3179_anvuew": "BandSplit Roformer — Mag (3179) · Anvuew",
            "mdx:bs_karaoke_becruily": ("BandSplit Roformer — Karaoke · Becruily & Frazer"),
            "mdx:bs_gtr_xlancer": "BandSplit Roformer — Guitar · Kimberley Xlance",
            "mdx:bs_siamese_vocals_unwa": "BandSplit Roformer — Siamese Vocals · Unwa",
            "mdx:bs_inst_exp_vlp_unwa": (
                "BandSplit Roformer — Instrumental EXP Value Residual · Unwa"
            ),
            "mdx:melband_roformer_inst_metal_prev_by_mesk": (
                "MelBand Roformer — Instrumental Metal Preview · Mesk"
            ),
            "mdx:mbr_xeno": "MelBand Roformer — Xeno · DrYound3r",
            "mdx:mbr_denoise_children_phaedrus33": (
                "MelBand Roformer — DeNoiser Children 16 kHz · Phaedrus33"
            ),
            "mdx:UVR_MDXNET_9482": "MDX-Net — UVR 9482",
            "mdx:model_mdx23c_ep_271_l1_freq_72.2383": (
                "MDX23C — Phantom Centre Extraction · WesleyR36"
            ),
        }
        for model_id, display in expected.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(project_model_display(model_id), display)
        self.assertEqual(
            project_model_display(
                "mdx:model_BandSplit-Roformer_Karaoke_Frazer_by-becruily",
                source_label=("Roformer Model: BandSplit Roformer | Karaoke Frazer by becruily"),
            ),
            "BandSplit Roformer — Karaoke Frazer · Becruily",
        )

    def test_projector_uses_reviewed_mdx_engine_specific_aliases(self) -> None:
        expected = {
            "mdx:MDX23C-8KFFT-InstVoc_HQ": ("MDX23C — 8K FFT Instrumental/Vocals HQ"),
            "mdx:MDX23C-8KFFT-InstVoc_HQ_2": ("MDX23C — 8K FFT Instrumental/Vocals HQ 2"),
            "mdx:UVR-MDX-NET-Inst_HQ_4": "MDX-Net — UVR Instrumental HQ 4",
            "mdx:Kim_Vocal_1": "MDX-Net — Kim Vocals 1",
            "mdx:Kim_Vocal_2": "MDX-Net — Kim Vocals 2",
        }
        for model_id, display in expected.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(project_model_display(model_id), display)

    def test_projector_uses_reviewed_viperx_series_names(self) -> None:
        expected = {
            "mdx:model_bs_roformer_ep_937_sdr_10.5309": (
                "BandSplit Roformer — Drum/Bass Separation (SDR 10.53) · ViperX"
            ),
            "mdx:model_bs_roformer_ep_368_sdr_12.9628": ("BandSplit Roformer — ViperX 12.96"),
            "mdx:model_bs_roformer_ep_317_sdr_12.9755": ("BandSplit Roformer — ViperX 12.97"),
            "mdx:model_mel_band_roformer_ep_3005_sdr_11.4360": (
                "MelBand Roformer — Vocals (SDR 11.44) · ViperX"
            ),
        }
        for model_id, display in expected.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(project_model_display(model_id), display)

    def test_projector_uses_reviewed_vr_utility_names(self) -> None:
        expected = {
            "vr:UVR-De-Echo-Aggressive": "UVR De-Echo — Aggressive · FoxJoy",
            "vr:UVR-De-Echo-Normal": "UVR De-Echo — Normal · FoxJoy",
            "vr:UVR-DeEcho-DeReverb": "UVR De-Echo/DeReverb · FoxJoy",
            "vr:UVR-DeNoise": "UVR DeNoise · FoxJoy",
            "vr:UVR-DeNoise-Lite": "UVR DeNoise Lite · FoxJoy",
            "vr:UVR-De-Reverb-aufr33-jarredou": "UVR DeReverb · Aufr33 & Jarredou",
        }
        for model_id, display in expected.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(project_model_display(model_id), display)
        self.assertEqual(project_model_display("vr:3_HP-Vocal-UVR"), "HP Vocals 3")
        self.assertEqual(project_model_display("vr:4_HP-Vocal-UVR"), "HP Vocals 4")

    def test_projector_uses_the_reviewed_mega_template(self) -> None:
        terms = {
            "full": "Full",
            "accordion": "Accordion Only",
            "acoustic-guitar": "Acoustic Guitar Only",
            "back-vocal": "Backing Vocals Only",
            "banjo": "Banjo Only",
            "bass": "Bass Only",
            "bassoon": "Bassoon Only",
            "bells": "Bells Only",
            "bowed_strings": "Bowed Strings Only",
            "brass": "Brass Only",
            "cello": "Cello Only",
            "clarinet": "Clarinet Only",
            "congas": "Congas Only",
            "digital-piano": "Digital Piano Only",
            "dobro": "Dobro Only",
            "double-bass": "Double Bass Only",
            "drums": "Drums Only",
            "electric-guitar": "Electric Guitar Only",
            "flute": "Flute Only",
            "french-horn": "French Horn Only",
            "glockenspiel": "Glockenspiel Only",
            "guitar": "Guitar Only",
            "harmonica": "Harmonica Only",
            "harp": "Harp Only",
            "harpsichord": "Harpsichord Only",
            "hh": "Hi-Hat Only",
            "keys": "Keys Only",
            "kick": "Kick Only",
            "lead-vocal": "Lead Vocals Only",
            "mandolin": "Mandolin Only",
            "marimba": "Marimba Only",
            "oboe": "Oboe Only",
            "organ": "Organ Only",
            "percussion": "Percussion Only",
            "piano": "Piano Only",
            "saxophone": "Saxophone Only",
            "sitar": "Sitar Only",
            "snare": "Snare Only",
            "strings": "Strings Only",
            "synth": "Synth Only",
            "tambourine": "Tambourine Only",
            "timpani": "Timpani Only",
            "toms": "Toms Only",
            "triangle": "Triangle Only",
            "trombone": "Trombone Only",
            "trumpet": "Trumpet Only",
            "tuba": "Tuba Only",
            "ukulele": "Ukulele Only",
            "viola": "Viola Only",
            "violin": "Violin Only",
            "vocal": "Vocals Only",
            "wind": "Wind Only",
            "wind-chimes": "Wind Chimes Only",
            "woodwind": "Woodwind Only",
        }
        self.assertEqual(len(terms), 54)
        for slug, variant in terms.items():
            model_id = f"mdx:bs_mega_53stem_{slug}_mvsep"
            expected = f"BandSplit Roformer — Mega {variant} (53 Stems) · MVSep"
            with self.subTest(model_id=model_id):
                self.assertEqual(project_model_display(model_id), expected)

    def test_reviewed_collision_and_author_distinctions_remain_unique(self) -> None:
        displays = {
            project_model_display("mdx:mbr_instfv9_gabox"),
            project_model_display("mdx:mbr_inst_becruily"),
            project_model_display("mdx:mbr_karaoke_fusion_aggr_gonzaluigi"),
            project_model_display("mdx:mbr_bve_gonzaluigi"),
            project_model_display("mdx:model_MelBand-Roformer_BVE_by-Gonza"),
        }
        self.assertEqual(len(displays), 5)


if __name__ == "__main__":
    unittest.main()
