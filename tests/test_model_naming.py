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
            "BandSplit Roformer — (4 Stems) Fine-Tuned Instrumental/Vocals High Quality · ViperX",
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


if __name__ == "__main__":
    unittest.main()
