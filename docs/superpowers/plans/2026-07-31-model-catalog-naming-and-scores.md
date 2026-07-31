# Unified Model Catalogue Naming and Scores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every catalogue model one canonical display name in both the Download Center and the runtime pickers, and replace the near-empty regex-scraped SDR with real benchmarked scores plus a metadata fallback so unscored rows still say something.

**Architecture:** A single `core/catalog_sources.py` owns the merge of all four catalogue sources and is consumed by both `DownloadManager` and `model_display`, closing the drift that made mvsepless/extras models render as raw basenames. Naming becomes one pure function in `core/model_naming.py`; scoring gains a real backend keyed by checkpoint filename in `core/model_scores.py`.

**Tech Stack:** Python 3, stdlib `unittest`, GTK4/libadwaita (UI layer only), `urllib` for catalogue fetches.

## Cross-plan dependency

Task 1 of [2026-07-31-ensemble-stem-semantics.md](2026-07-31-ensemble-stem-semantics.md) — the pure `ensemble_stem_bucket` resolver — **must land before Task 2 and Task 6 here.** Both plans answer "what stem does this model produce", and without the shared resolver this plan ships a second, subtly different answer: a 2-stem model whose yaml target is `other` (`mbr_inst2_unwa`, `melband_roformer_inst_v1e_plus`) would show no SDR badge despite the benchmark having an `instrumental` score for it.

The two affected steps are marked **CROSS-PLAN** inline below.

## Global Constraints

- **Catalogue labels remain the identity key.** `available_downloads`, `resolve`, `download` and the Download Center row keys all key on the raw catalogue label. Canonical names are presentation only — never write a canonical name back into `_uvr_model_name`, a row key, or anything `resolve()` sees.
- **No tkinter anywhere.** `core/` must stay framework-agnostic.
- **No network at import time, and none in `catalog_sources`.** It reads only the disk caches `politrees_catalog` and `mvsepless_catalog` already maintain.
- **Heavy imports stay lazy.** Do not import `torch`, `onnxruntime` or `engines` from any module touched here.
- **Upstream-wins merge order is fixed:** upstream → politrees → extras → mvsepless, then dedupe. Never reorder.
- **Keep the `Seperate*` misspelling** and the verbatim strings in `bundled/error_handling.py`.
- Tests are **stdlib unittest**, run with `.venv/bin/python -m unittest`. No pytest.
- Type checking is pyright `basic` over `ui/ core/ engines/ tests/ bundled/ ml/ scripts/`. Run `.venv/bin/python -m pyright` before the final commit.
- Search with `rg`, never `grep`.
- Never run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash` or `git clean` — this tree carries long-lived uncommitted edits under `models/*/model_data/`. Stage explicit paths only; never `git add -A`.

## File Structure

| File | Responsibility |
| --- | --- |
| `core/model_naming.py` (new) | Pure `canonical_display_name(label)`. The only place that decides what a model is called. |
| `core/model_scores.py` (modify) | Real SDR backend: fetch/cache/bundled fallback, per-stem aggregation, lookup by any filename. Keeps the regex as fallback. |
| `core/catalog_sources.py` (new) | The single merge. Returns merged catalogues + `{label: EntryMeta}`. |
| `core/mvsepless_catalog.py` (modify) | Stop discarding `stems`/`target_instrument`/`category`; add the Russian category table. |
| `core/downloads.py` (modify) | `_merge_politrees_supplement` becomes a thin caller of `catalog_sources`. |
| `core/model_display.py` (modify) | Index builders read `catalog_sources`. Existing `sanitize_*` / `build_*_display_index` helpers stay — other modules match on them. |
| `ui/download_center.py` (modify) | Canonical titles, subtitle fallback chain, stem-labelled SDR, sort by target-stem SDR. |
| `bundled/model_scores.json` (new) | Offline snapshot of the score data. |
| `bundled/constants/urls.py` (modify) | `MODEL_SCORES_URL`. |
| `core/paths.py` (modify) | `MODEL_SCORES_CACHE_FILE`. |

---

### Task 1: Canonical model naming

**Files:**
- Create: `core/model_naming.py`
- Create: `tests/test_model_naming.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `canonical_display_name(label: str) -> str`, `split_catalogue_prefix(label: str) -> Tuple[str, str]`, `strip_catalogue_prefix(label: str) -> str`, `canonical_family(text: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_naming.py`:

```python
"""Canonical display names across the four catalogue label dialects."""

import unittest

from core.model_naming import canonical_display_name, strip_catalogue_prefix


class StripCataloguePrefixTests(unittest.TestCase):
    def test_strips_download_center_category_prefixes(self) -> None:
        self.assertEqual(
            strip_catalogue_prefix("Roformer Model: BandSplit Roformer | HyperACE v2 by Unwa"),
            "BandSplit Roformer | HyperACE v2 by Unwa",
        )
        self.assertEqual(strip_catalogue_prefix("MDX23C Model VIP: Foo"), "Foo")
        self.assertEqual(strip_catalogue_prefix("SCnet: 4-stems Huge by Aname"), "4-stems Huge by Aname")

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
            "MelBand Roformer | Karaoke by Aufr33 & Viperx":
                "MelBand Roformer — Karaoke · Aufr33 & Viperx",
            "Roformer Model: BandSplit Roformer | HyperACE v2 Instrumental by Unwa":
                "BandSplit Roformer — HyperACE v2 Instrumental · Unwa",
            "Mel-Band Roformer Vocals by Kimberley Jensen":
                "MelBand Roformer — Vocals · Kimberley Jensen",
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_naming -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.model_naming'`

- [ ] **Step 3: Write the implementation**

Create `core/model_naming.py`:

```python
"""Canonical display names for catalogue models.

Four sources contribute labels in four house styles (upstream TRvlvr,
Politrees, ``bundled/extra_models.json``, mvsepless). This module is the only
place that decides what a model is *called*, so the Download Center and the
runtime method pickers cannot disagree.

Normalization is deliberately conservative: category prefixes are stripped,
architecture-family spellings are unified, and the author separator is
normalized. The descriptive middle of a label passes through verbatim, so no
model is ever renamed into something misleading.
"""

from __future__ import annotations

import re
from typing import Tuple

#: Rendered between the family and the descriptive title.
TITLE_SEPARATOR = " — "
#: Rendered between the title and the author.
AUTHOR_SEPARATOR = " · "

#: Download Center category prefixes. Longest-first so ``MDX23C Model VIP: ``
#: is matched before ``MDX23C Model: ``.
_CATEGORY_PREFIXES = (
    "VR Arch Single Model v5: ",
    "VR Arch Single Model v4: ",
    "VR Arch Single Model ",
    "VR Arch ",
    "MDX23C Model VIP: ",
    "MDX-Net Model VIP: ",
    "Roformer Model VIP: ",
    "MDX23C Model: ",
    "MDX-Net Model: ",
    "Roformer Model: ",
    "Apollo Model: ",
    "Bandit Plus: ",
    "Bandit v2: ",
    "MDX23C: ",
    "MDX-Net: ",
    "Bandit: ",
    "SCnet: ",
)

#: ``(regex, canonical family)`` — first match wins, so longer/more specific
#: families must come first.
_FAMILY_PATTERNS = (
    (re.compile(r"^mel[\s_-]?band[\s_-]?roformer\b", re.IGNORECASE), "MelBand Roformer"),
    (re.compile(r"^(?:bs|band[\s_-]?split)[\s_-]?roformer\b", re.IGNORECASE), "BandSplit Roformer"),
    (re.compile(r"^mdx23c\b", re.IGNORECASE), "MDX23C"),
    (re.compile(r"^scnet\b", re.IGNORECASE), "SCNet"),
    (re.compile(r"^bandit\b", re.IGNORECASE), "Bandit"),
    (re.compile(r"^apollo\b", re.IGNORECASE), "Apollo"),
)

#: ``by <author>`` at the end of a label, in any of the four dialects — or the
#: canonical ``· <author>`` this function itself emits, which is what makes
#: ``canonical_display_name`` idempotent.
_AUTHOR_RE = re.compile(
    r"(?:\s+by[\s_-]+|\s*\u00b7\s*)(?P<author>[^|\u00b7]+?)\s*$", re.IGNORECASE
)

_DEMUCS_RE = re.compile(r"^Demucs (v\d+): (.+)$", re.IGNORECASE)


#: Category prefixes that themselves declare a family. ``Roformer Model: `` is
#: absent on purpose: it does not say *which* Roformer, and the remainder does.
_PREFIX_FAMILIES = {
    "SCnet: ": "SCNet",
    "MDX23C Model VIP: ": "MDX23C",
    "MDX23C Model: ": "MDX23C",
    "MDX23C: ": "MDX23C",
    "MDX-Net Model VIP: ": "MDX-Net",
    "MDX-Net Model: ": "MDX-Net",
    "MDX-Net: ": "MDX-Net",
    "Bandit Plus: ": "Bandit",
    "Bandit v2: ": "Bandit",
    "Bandit: ": "Bandit",
    "Apollo Model: ": "Apollo",
}


def split_catalogue_prefix(label: str) -> Tuple[str, str]:
    """Return ``(family_from_prefix, remainder)`` for a catalogue label.

    The category prefix is often the only place the family is named — the
    remainder of ``SCnet: 4-stems Huge SCNet Bleedless by Aname`` starts with
    ``4-stems``, so dropping the prefix would lose the family entirely.
    """
    text = str(label or "").strip()
    family = ""
    for prefix in _CATEGORY_PREFIXES:
        if text.lower().startswith(prefix.lower()):
            family = _PREFIX_FAMILIES.get(prefix, "")
            text = text[len(prefix):].strip()
            break
    if text.lower().endswith(".ckpt"):
        text = text[: -len(".ckpt")].strip()
    return family, text


def strip_catalogue_prefix(label: str) -> str:
    """Remove a Download Center category prefix and a trailing ``.ckpt``."""
    return split_catalogue_prefix(label)[1]


def canonical_family(text: str) -> str:
    """Return the canonical family name a label starts with, or ``""``."""
    stripped = str(text or "").lstrip()
    for pattern, family in _FAMILY_PATTERNS:
        if pattern.match(stripped):
            return family
    return ""


def canonical_display_name(label: str) -> str:
    """Return the canonical display name for a catalogue label.

    Idempotent: running it over its own output is a no-op, so a label that has
    already been canonicalized upstream is safe to pass through again.
    """
    prefix_family, text = split_catalogue_prefix(label)
    if not text:
        return ""

    match = _DEMUCS_RE.match(text)
    if match:
        return f"{match.group(1)}{TITLE_SEPARATOR}{match.group(2)}"

    author = ""
    author_match = _AUTHOR_RE.search(text)
    if author_match:
        author = author_match.group("author").strip()
        text = text[: author_match.start()].strip()

    # Already canonical (contains the title separator): keep the head verbatim
    # as the family. This is what makes the function idempotent for families
    # that canonical_family cannot re-detect, such as MDX-Net and Demucs vN.
    if TITLE_SEPARATOR in text:
        head, _, tail = text.partition(TITLE_SEPARATOR)
        return _join(head.strip(), tail, author)

    # A family named by the remainder wins; the prefix is the fallback.
    family = canonical_family(text)
    if not family and prefix_family and not text.lower().startswith(prefix_family.lower()):
        return _join(prefix_family, text, author)
    if family:
        pattern = next(p for p, f in _FAMILY_PATTERNS if f == family)
        remainder = pattern.sub("", text.lstrip(), count=1)
    else:
        remainder = text
    # Both dialect separators collapse to whitespace before re-rendering.
    remainder = remainder.replace("|", " ")
    remainder = remainder.replace(TITLE_SEPARATOR.strip(), " ")
    remainder = remainder.replace(AUTHOR_SEPARATOR.strip(), " ")
    remainder = re.sub(r"\s+", " ", remainder).strip(" -—")

    if family and remainder:
        title = f"{family}{TITLE_SEPARATOR}{remainder}"
    elif family:
        title = family
    else:
        title = remainder

    if author:
        title = f"{title}{AUTHOR_SEPARATOR}{author}"
    return title


def _join(family: str, remainder: str, author: str) -> str:
    text = re.sub(r"\s+", " ", remainder.replace("|", " ")).strip(" -\u2014")
    title = f"{family}{TITLE_SEPARATOR}{text}" if text else family
    return f"{title}{AUTHOR_SEPARATOR}{author}" if author else title
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_model_naming -v`
Expected: PASS across `StripCataloguePrefixTests` and `CanonicalDisplayNameTests`

- [ ] **Step 5: Sweep the whole catalogue**

Unit tests cover the dialects; this catches anything they missed across all 461
real entries.

```bash
.venv/bin/python -c "
import collections
from core.model_naming import canonical_display_name as c
from core.downloads import DownloadManager
dm = DownloadManager(); dm.ensure_catalogues()
labels = []
for cat in (dm.vr_download_list, dm.mdx_download_list, dm.demucs_download_list, dm.apollo_download_list):
    labels += list(cat)
bad = [l for l in labels if c(c(l)) != c(l)]
empty = [l for l in labels if l.strip() and not c(l).strip()]
print('entries:', len(labels))
print('non-idempotent:', len(bad), bad[:3])
print('emptied:', len(empty), empty[:3])
fam = collections.Counter(c(l).split(' \u2014 ')[0] if ' \u2014 ' in c(l) else '(no family)' for l in labels)
for k, v in fam.most_common(12): print(f'  {v:4d}  {k}')
assert not bad and not empty
print('OK')
"
```

Expected: `non-idempotent: 0`, `emptied: 0`, then `OK`. The family histogram
should be dominated by `MelBand Roformer` and `BandSplit Roformer`, with
`(no family)` accounting for roughly the VR models, which genuinely have none.

- [ ] **Step 6: Commit**

```bash
git add core/model_naming.py tests/test_model_naming.py
git commit -m "feat(core): add canonical model display naming"
```

---

### Task 2: Real SDR scores backend

**Files:**
- Create: `bundled/model_scores.json` (fetched snapshot)
- Create: `tests/fixtures/model_scores_sample.json`
- Modify: `bundled/constants/urls.py`
- Modify: `core/paths.py:102` (add next to `MVSEPLESS_CACHE_FILE`)
- Modify: `core/model_scores.py`
- Modify: `tests/test_model_scores.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `load_model_scores(*, force: bool = False) -> Dict[str, Dict[str, float]]` — `{checkpoint_filename: {stem: mean_sdr}}`
  - `sdr_for_files(filenames: Iterable[str], scores: Optional[Mapping] = None) -> Dict[str, float]`
  - `primary_sdr(stem_scores: Mapping[str, float], target_stem: Optional[str] = None, *, stem_count: int = 2) -> Optional[Tuple[str, float]]` — **CROSS-PLAN:** the `stem_count` parameter and the bucket-based comparison come from the ensemble-semantics plan's Task 7. Implement `primary_sdr` in that form here rather than the simpler casefold version, or the two plans disagree.
  - `format_sdr_subtitle(sdr, size_text="", *, stem=None, extra="") -> str`
  - `model_scores_enabled() -> bool`

- [ ] **Step 1: Fetch the bundled snapshot and build the test fixture**

```bash
.venv/bin/python - <<'EOF'
import json, urllib.request, os
url = "https://raw.githubusercontent.com/nomadkaraoke/python-audio-separator/main/audio_separator/models-scores.json"
req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
data = json.loads(urllib.request.urlopen(req, timeout=30).read())
with open("bundled/model_scores.json", "w", encoding="utf-8") as fh:
    json.dump(data, fh, separators=(",", ":"))
print("snapshot entries:", len(data))

os.makedirs("tests/fixtures", exist_ok=True)
sample = {
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {
        "model_name": "Roformer Model: BS-Roformer-Viperx-1297",
        "track_scores": [
            {"track_name": "T1", "scores": {
                "vocals": {"SDR": 11.0, "SIR": 1.0},
                "instrumental": {"SDR": 16.0, "SIR": 1.0},
                "seconds_per_minute_m3": {"SDR": 999.0},
            }},
            {"track_name": "T2", "scores": {
                "vocals": {"SDR": 12.0},
                "instrumental": {"SDR": 16.5},
            }},
        ],
    },
    "htdemucs_ft.yaml": {
        "model_name": "Demucs v4: htdemucs_ft",
        "track_scores": [
            {"track_name": "T1", "scores": {
                "vocals": {"SDR": 9.0}, "drums": {"SDR": 10.0},
                "bass": {"SDR": 12.0}, "other": {"SDR": 8.0},
            }},
        ],
    },
    "UVR-DeNoise-Lite.pth": {"model_name": "VR Arch: UVR-DeNoise-Lite", "track_scores": []},
}
with open("tests/fixtures/model_scores_sample.json", "w", encoding="utf-8") as fh:
    json.dump(sample, fh, indent=1)
print("fixture written")
EOF
```

Expected: `snapshot entries: 115` (or higher if upstream has grown), then `fixture written`.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_model_scores.py` (keep the existing `ParseSdrScoreTests` and `PurposeAndSortTests` classes — they cover the regex fallback, which stays):

```python
import json
import os
import unittest.mock

from core import model_scores

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "model_scores_sample.json")


def _sample() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as handle:
        return json.load(handle)


class ModelScoreAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        model_scores.clear_model_scores_cache()
        self.addCleanup(model_scores.clear_model_scores_cache)

    def _loaded(self) -> dict:
        with unittest.mock.patch.object(model_scores, "_fetch_model_scores", return_value=_sample()):
            return model_scores.load_model_scores(force=True)

    def test_mean_sdr_per_stem(self) -> None:
        scores = self._loaded()
        entry = scores["model_bs_roformer_ep_317_sdr_12.9755.ckpt"]
        self.assertAlmostEqual(entry["vocals"], 11.5)
        self.assertAlmostEqual(entry["instrumental"], 16.25)

    def test_speed_metric_is_not_a_stem(self) -> None:
        scores = self._loaded()
        entry = scores["model_bs_roformer_ep_317_sdr_12.9755.ckpt"]
        self.assertNotIn("seconds_per_minute_m3", entry)

    def test_zero_track_model_is_unscored_not_an_error(self) -> None:
        scores = self._loaded()
        self.assertEqual(scores.get("UVR-DeNoise-Lite.pth", {}), {})

    def test_lookup_matches_demucs_yaml_key(self) -> None:
        scores = self._loaded()
        found = model_scores.sdr_for_files(
            ["955717e8-8726e21a.th", "htdemucs_ft.yaml"], scores=scores
        )
        self.assertAlmostEqual(found["drums"], 10.0)

    def test_lookup_is_case_insensitive(self) -> None:
        scores = self._loaded()
        found = model_scores.sdr_for_files(["HTDEMUCS_FT.YAML"], scores=scores)
        self.assertAlmostEqual(found["bass"], 12.0)

    def test_lookup_miss_returns_empty(self) -> None:
        scores = self._loaded()
        self.assertEqual(model_scores.sdr_for_files(["nope.ckpt"], scores=scores), {})


class PrimarySdrTests(unittest.TestCase):
    def test_target_stem_wins(self) -> None:
        result = model_scores.primary_sdr({"vocals": 11.5, "instrumental": 16.25}, "vocals")
        self.assertEqual(result, ("vocals", 11.5))

    def test_falls_back_to_highest_when_no_target(self) -> None:
        result = model_scores.primary_sdr({"vocals": 11.5, "instrumental": 16.25}, None)
        self.assertEqual(result, ("instrumental", 16.25))

    def test_unknown_target_falls_back(self) -> None:
        result = model_scores.primary_sdr({"vocals": 11.5}, "guitar")
        self.assertEqual(result, ("vocals", 11.5))

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(model_scores.primary_sdr({}, "vocals"))


class SdrSubtitleTests(unittest.TestCase):
    def test_stem_is_named(self) -> None:
        self.assertEqual(
            model_scores.format_sdr_subtitle(11.43, "1.2 GB", stem="vocals"),
            "vocals 11.4 SDR · 1.2 GB",
        )

    def test_falls_back_to_extra_when_unscored(self) -> None:
        self.assertEqual(
            model_scores.format_sdr_subtitle(None, "890 MB", extra="vocals, other"),
            "vocals, other · 890 MB",
        )

    def test_size_only(self) -> None:
        self.assertEqual(model_scores.format_sdr_subtitle(None, "890 MB"), "890 MB")

    def test_bare_sdr_without_stem_still_renders(self) -> None:
        self.assertEqual(model_scores.format_sdr_subtitle(11.43, ""), "11.4 SDR")


class ModelScoresDisabledTests(unittest.TestCase):
    def setUp(self) -> None:
        model_scores.clear_model_scores_cache()
        self.addCleanup(model_scores.clear_model_scores_cache)

    def test_kill_switch_returns_empty(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"UVR_DISABLE_MODEL_SCORES": "1"}):
            self.assertEqual(model_scores.load_model_scores(force=True), {})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_scores -v`
Expected: FAIL with `AttributeError: module 'core.model_scores' has no attribute 'clear_model_scores_cache'`

- [ ] **Step 4: Add the URL constant**

In `bundled/constants/urls.py`, after `MVSEPLESS_MODELS_JSON_URL` (line 26):

```python
#: Benchmarked per-stem SDR scores, keyed by checkpoint filename.
MODEL_SCORES_URL = (
    "https://raw.githubusercontent.com/nomadkaraoke/python-audio-separator"
    "/main/audio_separator/models-scores.json"
)
```

- [ ] **Step 5: Add the cache path**

In `core/paths.py`, after `MVSEPLESS_CACHE_FILE` (line 102):

```python
MODEL_SCORES_CACHE_FILE = os.path.join(CACHE_DIR, "model_scores.json")
```

- [ ] **Step 6: Write the scores backend**

Add to `core/model_scores.py`. Keep every existing function — the regex scraper stays as the fallback for models whose SDR lives only in their filename. Replace only `format_sdr_subtitle`.

```python
import json
import os
import statistics
import time
from typing import Any, Dict, Mapping, Tuple

from bundled.constants import MODEL_SCORES_URL

from . import paths
from .debug_log import debug

_SCORES_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

#: Present in the score data as a speed measurement, not a separable stem.
_NON_STEM_KEYS = frozenset({"seconds_per_minute_m3"})

_BUNDLED_SCORES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bundled",
    "model_scores.json",
)

_cached_scores: Optional[Dict[str, Dict[str, float]]] = None
_cached_loaded_at: float = 0.0


def model_scores_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_MODEL_SCORES", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def clear_model_scores_cache() -> None:
    global _cached_scores, _cached_loaded_at
    _cached_scores = None
    _cached_loaded_at = 0.0


def _cache_path() -> str:
    return paths.migrate_cache_file("model_scores.json", paths.MODEL_SCORES_CACHE_FILE)


def _read_disk_cache() -> Optional[Dict[str, Any]]:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            if (time.time() - float(payload.get("fetched_at") or 0)) < _SCORES_CACHE_TTL_SECONDS:
                return payload["data"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_disk_cache(data: Mapping[str, Any]) -> None:
    try:
        cache_path = _cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "data": data}, handle)
    except OSError as exc:
        debug("download", f"model scores cache write failed err={exc}")


def _read_bundled_scores() -> Dict[str, Any]:
    try:
        with open(_BUNDLED_SCORES_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _fetch_model_scores() -> Optional[Dict[str, Any]]:
    """Network fetch, isolated so tests can patch exactly this call."""
    from .mdx_config_fetch import _urlopen

    try:
        with _urlopen(MODEL_SCORES_URL) as response:
            payload = json.load(response)
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        debug("download", f"model scores fetch failed err={type(exc).__name__}: {exc}")
        return None


def _aggregate_entry(entry: Mapping[str, Any]) -> Dict[str, float]:
    """Mean SDR per stem across an entry's tracks."""
    per_stem: Dict[str, list] = {}
    for track in entry.get("track_scores") or []:
        if not isinstance(track, dict):
            continue
        for stem, metrics in (track.get("scores") or {}).items():
            if stem in _NON_STEM_KEYS or not isinstance(metrics, dict):
                continue
            value = metrics.get("SDR")
            if isinstance(value, (int, float)):
                per_stem.setdefault(str(stem), []).append(float(value))
    return {stem: round(statistics.mean(vals), 2) for stem, vals in per_stem.items() if vals}


def load_model_scores(*, force: bool = False) -> Dict[str, Dict[str, float]]:
    """Return ``{checkpoint_filename: {stem: mean_sdr}}``, lowercased keys.

    Live fetch, then the seven-day disk cache, then the bundled snapshot, so
    the badge works offline and in CI.
    """
    global _cached_scores, _cached_loaded_at

    if not model_scores_enabled():
        return {}

    now = time.time()
    if (
        not force
        and _cached_scores is not None
        and (now - _cached_loaded_at) < _SCORES_CACHE_TTL_SECONDS
    ):
        return _cached_scores

    raw = _read_disk_cache() if not force else None
    if raw is None:
        raw = _fetch_model_scores()
        if raw is not None:
            _write_disk_cache(raw)
    if raw is None:
        raw = _read_disk_cache() or _read_bundled_scores()

    aggregated = {
        str(name).casefold(): _aggregate_entry(entry)
        for name, entry in (raw or {}).items()
        if isinstance(entry, dict)
    }
    _cached_scores = aggregated
    _cached_loaded_at = now
    debug("download", f"model scores loaded entries={len(aggregated)}")
    return aggregated


def sdr_for_files(
    filenames: Iterable[str],
    scores: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> Dict[str, float]:
    """Return per-stem SDR for the first filename with a score.

    Matches on *any* filename in a catalogue entry, not just the primary
    checkpoint: Demucs v4 is keyed in the score data by its ``.yaml``.
    """
    table = load_model_scores() if scores is None else scores
    if not table:
        return {}
    for name in filenames:
        entry = table.get(os.path.basename(str(name)).casefold())
        if entry:
            return dict(entry)
    return {}


def primary_sdr(
    stem_scores: Mapping[str, float],
    target_stem: Optional[str] = None,
    *,
    stem_count: int = 2,
) -> Optional[Tuple[str, float]]:
    """Return ``(stem, sdr)`` for the model's headline score.

    CROSS-PLAN: both the model's target stem and the score-data keys go through
    :func:`ensemble_stem_bucket` before comparison. The score data keys stems
    lowercase (``vocals``, ``instrumental``, ``other``) while a model's target
    is whatever its yaml said, so a raw casefold comparison still misses: a
    2-stem model targeting ``other`` means *instrumental* and would find no
    score at all. ``stem_count`` is what disambiguates that from a 4-stem
    model's genuine ``other`` residual.

    The returned stem is the **score-data key**, not the bucket, so callers
    render the name the benchmark actually used.
    """
    from .model_stem_semantics import BUCKET_UNKNOWN, ensemble_stem_bucket

    if not stem_scores:
        return None
    if target_stem:
        wanted = ensemble_stem_bucket(target_stem, stem_count=stem_count)
        if wanted != BUCKET_UNKNOWN:
            for stem, value in stem_scores.items():
                if ensemble_stem_bucket(stem, stem_count=stem_count) == wanted:
                    return (stem, value)
    stem, value = max(stem_scores.items(), key=lambda item: item[1])
    return (stem, value)
```

**CROSS-PLAN:** this requires `ensemble_stem_bucket` from the ensemble-semantics plan's Task 1. If that has not landed, stop and do it first — the simpler casefold version will need rewriting and its tests will encode the wrong behaviour.

Then replace the existing `format_sdr_subtitle` (currently at line 120) with:

```python
def format_sdr_subtitle(
    sdr: Optional[float],
    size_text: str = "",
    *,
    stem: Optional[str] = None,
    extra: str = "",
) -> str:
    """Build a catalogue row subtitle: SDR (if known) -> extra -> size.

    ``stem`` names the stem the score belongs to. A bare number invites a
    comparison between different quantities: the same checkpoint can be 11.4
    on vocals and 16.0 on instrumental.
    """
    parts: List[str] = []
    if sdr is not None:
        parts.append(f"{stem} {sdr:.1f} SDR" if stem else f"{sdr:.1f} SDR")
    elif extra.strip():
        parts.append(extra.strip())
    size = (size_text or "").strip()
    if size:
        parts.append(size)
    return " · ".join(parts)
```

The existing import line is `from typing import Iterable, List, Optional, Sequence, Tuple` — extend it to `from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_model_scores -v`
Expected: PASS. If the pre-existing `test_format_sdr_subtitle` fails, it asserted the old `" · "` join with a bare SDR — the new `test_bare_sdr_without_stem_still_renders` covers that path, so update the old assertion to match rather than reverting the signature.

- [ ] **Step 8: Document the kill switch**

In `docs/environment.md`, next to the `UVR_DISABLE_POLITREES` / `UVR_DISABLE_MVSEPLESS` entries:

```markdown
- `UVR_DISABLE_MODEL_SCORES=1` — skip the benchmarked SDR catalogue (network
  fetch + seven-day cache); rows fall back to stems and size.
```

- [ ] **Step 9: Commit**

```bash
git add core/model_scores.py tests/test_model_scores.py tests/fixtures/model_scores_sample.json \
        bundled/model_scores.json bundled/constants/urls.py core/paths.py docs/environment.md
git commit -m "feat(core): back SDR badges with benchmarked per-stem scores"
```

---

### Task 3: Retain mvsepless entry metadata

**Files:**
- Modify: `core/mvsepless_catalog.py:233-303` (`convert_mvsepless_catalog`)
- Modify: `tests/test_mvsepless_catalog.py`

**Interfaces:**
- Consumes: `core.model_stem_semantics` intent constants (already imported by `model_scores`).
- Produces:
  - `convert_mvsepless_catalog(models)` gains a `"metadata"` key: `{label: {"entry_id", "model_type", "stems", "target_instrument", "category", "category_en", "intent"}}`
  - `mvsepless_metadata(converted=None) -> Dict[str, Dict[str, Any]]`
  - `translate_category(category: str) -> Tuple[str, str]` returning `(english_label, intent)`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mvsepless_catalog.py`:

```python
from core.mvsepless_catalog import convert_mvsepless_catalog, translate_category
from core.model_stem_semantics import INTENT_KARAOKE, INTENT_MULTI_STEM, INTENT_VOCALS


class CategoryTranslationTests(unittest.TestCase):
    def test_known_categories_translate_with_intent(self) -> None:
        self.assertEqual(translate_category("Вокал"), ("Vocals", INTENT_VOCALS))
        self.assertEqual(translate_category("Караоке"), ("Karaoke", INTENT_KARAOKE))
        self.assertEqual(translate_category("4 стема"), ("4 stems", INTENT_MULTI_STEM))

    def test_unknown_category_passes_through(self) -> None:
        label, intent = translate_category("Nonexistent")
        self.assertEqual(label, "Nonexistent")
        self.assertTrue(intent)


class MetadataSidecarTests(unittest.TestCase):
    def test_supported_entry_keeps_stems_and_target(self) -> None:
        converted = convert_mvsepless_catalog({
            "mbr_x": {
                "model_type": "mel_band_roformer",
                "category": "Вокал",
                "full_name": "Mel-Band Roformer X by Someone",
                "stems": ["Vocals", "other"],
                "target_instrument": "Vocals",
                "checkpoint_url": "https://example.invalid/a/mbr_x.ckpt",
                "config_url": "https://example.invalid/a/mbr_x.yaml",
            }
        })
        meta = converted["metadata"]["Mel-Band Roformer X by Someone"]
        self.assertEqual(meta["stems"], ["Vocals", "other"])
        self.assertEqual(meta["target_instrument"], "Vocals")
        self.assertEqual(meta["category_en"], "Vocals")
        self.assertEqual(meta["intent"], INTENT_VOCALS)
        self.assertEqual(meta["entry_id"], "mbr_x")

    def test_unsupported_entry_also_gets_metadata(self) -> None:
        converted = convert_mvsepless_catalog({
            "mbr_wsa": {
                "model_type": "mel_band_roformer",
                "category": "Вокал",
                "full_name": "WSA Mel-Band Roformer",
                "stems": ["other", "vocals"],
                "target_instrument": "vocals",
                "checkpoint_url": "https://example.invalid/a/mbr_wsa.ckpt",
                "config_url": "https://example.invalid/a/mbr_wsa.yaml",
            }
        })
        self.assertIn("WSA Mel-Band Roformer", converted["metadata"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_mvsepless_catalog -v`
Expected: FAIL with `ImportError: cannot import name 'translate_category'`

- [ ] **Step 3: Add the category table**

In `core/mvsepless_catalog.py`, after `_MODEL_TYPE_TO_ARCH` (line 102):

```python
from .model_stem_semantics import (
    INTENT_DRUM_BASS_SEP,
    INTENT_DUAL_VOC_INST,
    INTENT_INSTRUMENTAL,
    INTENT_KARAOKE,
    INTENT_MULTI_STEM,
    INTENT_SPECIAL_FX,
    INTENT_SPECIALTY_STEM,
    INTENT_UNKNOWN,
    INTENT_VOCALS,
)

#: mvsepless ``category`` values are Russian. Map each to an English label and
#: the stem-semantics intent, so the purpose filter uses real metadata instead
#: of regex-guessing from the label.
_CATEGORY_TABLE: Dict[str, Tuple[str, str]] = {
    "Вокал": ("Vocals", INTENT_VOCALS),
    "Инструментал": ("Instrumental", INTENT_INSTRUMENTAL),
    "Инструментал и вокал": ("Instrumental & vocals", INTENT_DUAL_VOC_INST),
    "Караоке": ("Karaoke", INTENT_KARAOKE),
    "4 стема": ("4 stems", INTENT_MULTI_STEM),
    "6 стемов": ("6 stems", INTENT_MULTI_STEM),
    "Все стемы": ("All stems", INTENT_MULTI_STEM),
    "Ударные": ("Drums", INTENT_DRUM_BASS_SEP),
    "Бас": ("Bass", INTENT_DRUM_BASS_SEP),
    "Басс": ("Bass", INTENT_DRUM_BASS_SEP),
    "DrumSep": ("DrumSep", INTENT_DRUM_BASS_SEP),
    "Реверб": ("Reverb", INTENT_SPECIAL_FX),
    "Эхо": ("Echo", INTENT_SPECIAL_FX),
    "Реверб и эхо": ("Reverb & echo", INTENT_SPECIAL_FX),
    "Шум": ("Noise", INTENT_SPECIAL_FX),
    "Звуковые эффекты": ("Sound effects", INTENT_SPECIAL_FX),
    "Дыхание": ("Breath", INTENT_SPECIAL_FX),
    "Разделение голосов": ("Voice separation", INTENT_VOCALS),
    "Мужской/Женский вокал": ("Male/female vocals", INTENT_VOCALS),
    "Дуэт": ("Duet", INTENT_VOCALS),
    "Хор": ("Choir", INTENT_SPECIALTY_STEM),
    "Гитара": ("Guitar", INTENT_SPECIALTY_STEM),
    "Клавишные": ("Keys", INTENT_SPECIALTY_STEM),
    "Перкуссия": ("Percussion", INTENT_SPECIALTY_STEM),
    "Оркестр": ("Orchestra", INTENT_SPECIALTY_STEM),
    "Синтезатор": ("Synth", INTENT_SPECIALTY_STEM),
    "Саксофон": ("Saxophone", INTENT_SPECIALTY_STEM),
    "Струнные": ("Strings", INTENT_SPECIALTY_STEM),
    "Щипковые струнные": ("Plucked strings", INTENT_SPECIALTY_STEM),
    "Смычковые струнные": ("Bowed strings", INTENT_SPECIALTY_STEM),
    "Духовые": ("Winds", INTENT_SPECIALTY_STEM),
    "Деревянные духовые": ("Woodwinds", INTENT_SPECIALTY_STEM),
    "Медные духовые": ("Brass", INTENT_SPECIALTY_STEM),
    "Гармоники": ("Harmonics", INTENT_SPECIALTY_STEM),
    "Звуки толпы": ("Crowd", INTENT_SPECIALTY_STEM),
    "Скретч": ("Scratch", INTENT_SPECIALTY_STEM),
    "Кинематограф": ("Cinematic", INTENT_SPECIALTY_STEM),
    "Объёмный звук": ("Surround", INTENT_SPECIALTY_STEM),
    "Фантомный центр": ("Phantom centre", INTENT_SPECIALTY_STEM),
    "Прочее": ("Other", INTENT_UNKNOWN),
}


def translate_category(category: str) -> Tuple[str, str]:
    """Return ``(english_label, intent)`` for an mvsepless category value."""
    text = str(category or "").strip()
    if text in _CATEGORY_TABLE:
        return _CATEGORY_TABLE[text]
    return (text, INTENT_UNKNOWN)
```

- [ ] **Step 4: Populate the metadata sidecar**

In `convert_mvsepless_catalog`, add `metadata: Dict[str, Dict[str, Any]] = {}` beside `unsupported_labels` (line 262), then inside the `for entry_id, entry in models.items()` loop, immediately after `arch = _MODEL_TYPE_TO_ARCH.get(...)` (line 271):

```python
        category_en, intent = translate_category(entry.get("category") or "")
        stems = entry.get("stems")
        metadata.setdefault(
            label,
            {
                "entry_id": str(entry_id),
                "model_type": model_type,
                "stems": list(stems) if isinstance(stems, list) else [],
                "target_instrument": entry.get("target_instrument") or None,
                "category": str(entry.get("category") or ""),
                "category_en": category_en,
                "intent": intent,
                "arch": arch,
            },
        )
```

`setdefault` keeps the first label's metadata, matching the upstream-wins rule the label merge already follows. Placing it before the `if not supported` branch means unsupported rows get metadata too.

Add `"metadata": metadata,` to the returned dict (line 297-303), and add this accessor after `unsupported_reason_for_label`:

```python
def mvsepless_metadata(
    converted: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return ``{label: metadata}`` for every mvsepless entry."""
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return {}
    meta = data.get("metadata") or {}
    return dict(meta) if isinstance(meta, dict) else {}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_mvsepless_catalog -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/mvsepless_catalog.py tests/test_mvsepless_catalog.py
git commit -m "feat(core): retain mvsepless stems, target and category metadata"
```

---

### Task 4: The single merged-catalogue provider

**Files:**
- Create: `core/catalog_sources.py`
- Create: `tests/test_catalog_sources.py`
- Modify: `core/downloads.py:321-367` (`_merge_politrees_supplement`)

**Interfaces:**
- Consumes: `mvsepless_metadata` (Task 3), `canonical_display_name` (Task 1).
- Produces:
  - `MergedCatalogues` dataclass with fields `vr`, `mdx`, `demucs`, `apollo` (each `Dict[str, Any]`) and `meta` (`Dict[str, EntryMeta]`)
  - `EntryMeta` dataclass: `label`, `display`, `arch`, `source`, `files` (`Dict[str, str]`), `checkpoint` (`Optional[str]`), `stems` (`List[str]`), `target_instrument` (`Optional[str]`), `intent` (`str`)
  - `merged_catalogues(*, vr, mdx, demucs, force=False) -> MergedCatalogues`
  - metadata reaches consumers via `DownloadManager.catalogue_meta`, not a module global

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog_sources.py`:

```python
"""The single merge path shared by Download Center and the runtime pickers."""

import unittest
import unittest.mock

from core import catalog_sources

#: ``_supplemental_sources`` takes no arguments and returns supplements only,
#: so patching it leaves the real base merge under test.
_NO_SUPPLEMENTS = ({}, {}, {}, {})


def _with_supplements(supplements):
    return unittest.mock.patch.object(
        catalog_sources, "_supplemental_sources", return_value=supplements
    )


class MergeOrderTests(unittest.TestCase):
    def test_upstream_label_is_never_overwritten(self) -> None:
        with _with_supplements(({}, {"Shared": {"other.ckpt": "u2"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"Shared": {"first.ckpt": "u1"}}, demucs={}
            )
        self.assertEqual(merged.mdx["Shared"], {"first.ckpt": "u1"})

    def test_supplemental_entries_are_added(self) -> None:
        with _with_supplements(({}, {"New": {"new.ckpt": "u2"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIn("New", merged.mdx)

    def test_base_and_supplement_both_survive(self) -> None:
        with _with_supplements(({}, {"FromSupplement": {"b.ckpt": "u"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"FromBase": {"a.ckpt": "u"}}, demucs={}
            )
        self.assertEqual(set(merged.mdx), {"FromBase", "FromSupplement"})

    def test_vr_and_demucs_merge_independently(self) -> None:
        with _with_supplements(({"V": "v.pth"}, {}, {"D": {"d.yaml": "u"}}, {})):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIn("V", merged.vr)
        self.assertIn("D", merged.demucs)


class EntryMetaTests(unittest.TestCase):
    def test_meta_carries_canonical_display_and_checkpoint(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={},
                mdx={"Roformer Model: Mel-Band Roformer | Inst v2 by Unwa":
                     {"mbr_inst2_unwa.ckpt": "u", "mbr_inst2_unwa.yaml": "c"}},
                demucs={},
            )
        meta = merged.meta["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        self.assertEqual(meta.display, "MelBand Roformer — Inst v2 · Unwa")
        self.assertEqual(meta.checkpoint, "mbr_inst2_unwa.ckpt")
        self.assertEqual(meta.files["mbr_inst2_unwa.yaml"], "c")

    def test_mvsepless_metadata_reaches_meta(self) -> None:
        with _with_supplements(
            ({}, {"M": {"m.ckpt": "u", "m.yaml": "c"}}, {},
             {"M": {"stems": ["Vocals", "other"],
                    "target_instrument": "Vocals",
                    "intent": "vocals"}})
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, ["Vocals", "other"])
        self.assertEqual(meta.target_instrument, "Vocals")

    def test_entry_without_mvsepless_metadata_still_gets_meta(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"Plain": {"p.ckpt": "u"}}, demucs={}
            )
        meta = merged.meta["Plain"]
        self.assertEqual(meta.stems, [])
        self.assertIsNone(meta.target_instrument)

    def test_vr_plain_string_value_becomes_a_files_map(self) -> None:
        # VR catalogue entries are bare filenames, not {file: url} dicts.
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"}, mdx={}, demucs={}
            )
        meta = merged.meta["VR Arch Single Model v5: 1_HP-UVR"]
        self.assertEqual(meta.checkpoint, "1_HP-UVR.pth")

    def test_meta_covers_every_arch(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={"V": "v.pth"}, mdx={"M": {"m.ckpt": "u"}}, demucs={"D": {"d.yaml": "u"}}
            )
        for label in ("V", "M", "D"):
            with self.subTest(label=label):
                self.assertIn(label, merged.meta)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_catalog_sources -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.catalog_sources'`

- [ ] **Step 3: Write the implementation**

Create `core/catalog_sources.py`:

```python
"""The single merge of every catalogue source.

Before this module there were two independent merge paths — ``DownloadManager``
merged upstream + politrees + extras + mvsepless, while the runtime display
index read only upstream + politrees. They drifted, and models installed from
the two newest sources rendered as raw basenames in the method pickers.

Both consumers now read this module, so a fifth source cannot reintroduce that
class of bug. Only disk caches are read here: no network, so populating a model
dropdown stays fast and works offline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)

from .catalog_dedupe import dedupe_download_catalogue
from .debug_log import debug
from .extra_catalog import apollo_download_list, merge_extra_catalogues
from .model_naming import canonical_display_name
from .model_stem_semantics import INTENT_UNKNOWN
from .mvsepless_catalog import merge_mvsepless_catalogues, mvsepless_metadata
from .politrees_catalog import (
    load_politrees_links,
    merge_politrees_catalogues,
    merge_supplemental_list,
)


@dataclass(frozen=True)
class EntryMeta:
    """Everything known about one catalogue entry, keyed by its label."""

    label: str
    display: str
    arch: str
    files: Dict[str, str] = field(default_factory=dict)
    checkpoint: Optional[str] = None
    stems: List[str] = field(default_factory=list)
    target_instrument: Optional[str] = None
    intent: str = INTENT_UNKNOWN


@dataclass(frozen=True)
class MergedCatalogues:
    vr: Dict[str, Any]
    mdx: Dict[str, Any]
    demucs: Dict[str, Any]
    apollo: Dict[str, Any]
    meta: Dict[str, EntryMeta]


def _supplemental_sources() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Collect politrees + extras + mvsepless entries, **without** any base.

    Each merge helper is called with empty bases, so what comes back is the
    supplements alone, already ordered politrees > extras > mvsepless among
    themselves. :func:`merged_catalogues` then merges this under the caller's
    upstream catalogues, which keeps upstream-wins in exactly one place.

    Taking no arguments is deliberate: a version that received the base and
    returned it merged could not be substituted in a test without also
    substituting the merge under test.
    """
    vr: Dict[str, Any] = {}
    mdx: Dict[str, Any] = {}
    demucs: Dict[str, Any] = {}

    politrees = load_politrees_links()
    if politrees:
        vr, mdx, demucs = merge_politrees_catalogues(vr, mdx, demucs, politrees)
    vr, mdx, demucs = merge_extra_catalogues(vr, mdx, demucs)
    vr, mdx, demucs = merge_mvsepless_catalogues(vr, mdx, demucs)
    return dict(vr), dict(mdx), dict(demucs), mvsepless_metadata()


def _primary_checkpoint(files: Mapping[str, str]) -> Optional[str]:
    for name in files:
        if not str(name).endswith(".yaml"):
            return os.path.basename(str(name))
    for name in files:
        return os.path.basename(str(name))
    return None


def _build_meta(
    catalogue: Mapping[str, Any],
    arch: str,
    extra_meta: Mapping[str, Mapping[str, Any]],
) -> Dict[str, EntryMeta]:
    out: Dict[str, EntryMeta] = {}
    for label, model in catalogue.items():
        files: Dict[str, str] = (
            {str(k): str(v) for k, v in model.items()}
            if isinstance(model, dict)
            else {str(model): ""}
        )
        source_meta = extra_meta.get(label) or {}
        stems = source_meta.get("stems")
        out[label] = EntryMeta(
            label=label,
            display=canonical_display_name(label),
            arch=arch,
            files=files,
            checkpoint=_primary_checkpoint(files),
            stems=list(stems) if isinstance(stems, list) else [],
            target_instrument=source_meta.get("target_instrument") or None,
            intent=str(source_meta.get("intent") or INTENT_UNKNOWN),
        )
    return out


def merged_catalogues(
    *,
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    force: bool = False,
) -> MergedCatalogues:
    """Merge every source over the supplied upstream catalogues, then dedupe."""
    supp_vr, supp_mdx, supp_demucs, extra_meta = _supplemental_sources()

    # Upstream-wins, in one place: a label already in the base is never
    # replaced by a supplement.
    vr_out = merge_supplemental_list(vr, supp_vr)
    mdx_out = merge_supplemental_list(mdx, supp_mdx)
    demucs_out = merge_supplemental_list(demucs, supp_demucs)

    vr_out = dedupe_download_catalogue(vr_out)
    mdx_out = dedupe_download_catalogue(mdx_out)
    demucs_out = dedupe_download_catalogue(demucs_out, demucs_bags=True)
    apollo_out = dedupe_download_catalogue(apollo_download_list())

    meta: Dict[str, EntryMeta] = {}
    for catalogue, arch in (
        (vr_out, VR_ARCH_TYPE),
        (mdx_out, MDX_ARCH_TYPE),
        (demucs_out, DEMUCS_ARCH_TYPE),
        (apollo_out, APOLLO_ARCH_TYPE),
    ):
        meta.update(_build_meta(catalogue, arch, extra_meta))

    debug("download", f"catalog_sources merged entries={len(meta)}")
    return MergedCatalogues(
        vr=vr_out, mdx=mdx_out, demucs=demucs_out, apollo=apollo_out, meta=meta
    )


```

`merged_catalogues` is a pure function of its inputs plus the disk caches — it
holds no module state. Metadata reaches consumers through
`DownloadManager.catalogue_meta`, set in Task 4 Step 5. An earlier draft used a
module-global written as a side effect of the last merge, with a
`catalogue_meta_for_label` lookup; that made every reader depend on someone
having called the merge first, and returned "no metadata" instead of failing
when they had not.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_catalog_sources -v`
Expected: PASS

- [ ] **Step 5: Route DownloadManager through it**

In `core/downloads.py`, replace the body of `_merge_politrees_supplement` (lines 321-367) with:

```python
    def _merge_politrees_supplement(self) -> None:
        from .catalog_sources import merged_catalogues

        merged = merged_catalogues(
            vr=self.vr_download_list,
            mdx=self.mdx_download_list,
            demucs=self.demucs_download_list,
        )
        self.vr_download_list = merged.vr
        self.mdx_download_list = merged.mdx
        self.demucs_download_list = merged.demucs
        self.apollo_download_list = merged.apollo
        self.catalogue_meta = merged.meta
        existing_labels = {
            **self.vr_download_list,
            **self.mdx_download_list,
            **self.demucs_download_list,
            **self.apollo_download_list,
        }
        self.unsupported_download_list = unsupported_mvsepless_downloads(
            existing_labels=existing_labels
        )
```

Add `self.catalogue_meta: Dict[str, Any] = {}` (holding `EntryMeta` values; keep the annotation loose to avoid importing `catalog_sources` at module import time) to `__init__` beside `unsupported_download_list` (line 162). Remove the now-unused `merge_politrees_catalogues`, `merge_extra_catalogues`, `merge_mvsepless_catalogues`, `apollo_download_list`, `dedupe_download_catalogue` and `load_politrees_links` imports **only if** `rg -n "<name>" core/downloads.py` shows no other use — `load_politrees_links` and `dedupe_download_catalogue` may be referenced elsewhere in the file.

- [ ] **Step 6: Run the download suites to verify no regression**

Run: `.venv/bin/python -m unittest tests.test_core_downloads tests.test_catalog_dedupe tests.test_extra_catalog tests.test_download_center_state -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/catalog_sources.py tests/test_catalog_sources.py core/downloads.py
git commit -m "refactor(core): merge every catalogue source in one place"
```

---

### Task 5: Fix raw display names in the runtime pickers

**Files:**
- Modify: `core/model_display.py:40-93` (delete the three sanitizers), `:204-241` (index builders)
- Modify: `tests/test_model_display.py`

**Interfaces:**
- Consumes: `merged_catalogues` and `EntryMeta` (Task 4), `canonical_display_name` (Task 1).
- Produces: unchanged public signatures — `load_mdx_catalog_display_index()`, `load_vr_catalog_display_index()`, `load_demucs_catalog_display_index()` all still return `Dict[str, str]`.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_model_display.py`:

```python
class MvseplessAndExtrasDisplayTests(unittest.TestCase):
    """Regression: models from extras/mvsepless rendered as raw basenames.

    ``load_mdx_catalog_display_index`` read only the upstream cache and
    Politrees, so anything added by the two newest catalogue sources fell back
    to its on-disk basename in the method pickers.
    """

    #: Basenames observed rendering raw before the catalog_sources unification.
    RAW_BEFORE = (
        "bs_inst_hyperace2_unwa",
        "huge_scnet_4stems_bleedless",
        "huge_scnet_4stems_fullness",
        "mbr_inst2_unwa",
        "mbr_instfvx_gabox",
    )

    def test_previously_raw_basenames_now_resolve(self) -> None:
        from core.model_display import load_mdx_catalog_display_index

        index = load_mdx_catalog_display_index()
        missing = [name for name in self.RAW_BEFORE if name not in index]
        self.assertEqual(missing, [], f"still unnamed: {missing}")

    def test_resolved_names_are_canonical(self) -> None:
        from core.model_display import load_mdx_catalog_display_index

        index = load_mdx_catalog_display_index()
        display = index["mbr_inst2_unwa"]
        self.assertNotEqual(display, "mbr_inst2_unwa")
        self.assertNotIn("Roformer Model:", display)
```

This test needs the mvsepless and extras data. It reads the on-disk cache, so guard it the way the repo already guards network-dependent tests:

```python
    @classmethod
    def setUpClass(cls) -> None:
        from core.mvsepless_catalog import load_converted_mvsepless

        if not load_converted_mvsepless():
            raise unittest.SkipTest("mvsepless catalogue unavailable (no cache, no network)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_display.MvseplessAndExtrasDisplayTests -v`
Expected: FAIL — `still unnamed: ['bs_inst_hyperace2_unwa', 'huge_scnet_4stems_bleedless', 'huge_scnet_4stems_fullness', 'mbr_inst2_unwa', 'mbr_instfvx_gabox']`

- [ ] **Step 3: Rebuild the index off catalog_sources**

In `core/model_display.py`, replace `load_mdx_catalog_display_index`, `load_vr_catalog_display_index` and `load_demucs_catalog_display_index` (lines 204-241) with:

```python
def _merged_for_display():
    """Merged catalogues built from the upstream cache plus every supplement."""
    from .catalog_sources import merged_catalogues

    source = _load_manual_download_cache()
    mdx: Dict[str, Any] = {}
    for key in _MDX_CATALOG_SOURCE_KEYS:
        catalogue = source.get(key)
        if isinstance(catalogue, dict):
            mdx.update(catalogue)
    vr: Dict[str, Any] = {}
    for key in _VR_CATALOG_SOURCE_KEYS:
        catalogue = source.get(key)
        if isinstance(catalogue, dict):
            vr.update(catalogue)
    demucs: Dict[str, Any] = {}
    for key in _DEMUCS_CATALOG_SOURCE_KEYS:
        catalogue = source.get(key)
        if isinstance(catalogue, dict):
            demucs.update(catalogue)
    return merged_catalogues(vr=vr, mdx=mdx, demucs=demucs)


def _index_from_meta(catalogue: Mapping[str, Any], merged) -> Dict[str, str]:
    """Map every file basename in a catalogue to its canonical display name."""
    index: Dict[str, str] = {}
    for label in catalogue:
        meta = merged.meta.get(label)
        if meta is None:
            continue
        for filename in meta.files:
            stem = os.path.splitext(os.path.basename(filename))[0]
            index.setdefault(stem, meta.display)
    return index


def load_mdx_catalog_display_index() -> Dict[str, str]:
    """Build MDX checkpoint-basename→display-name index from every source."""
    merged = _merged_for_display()
    return _index_from_meta(merged.mdx, merged)


def load_vr_catalog_display_index() -> Dict[str, str]:
    """Build VR basename→runtime-display index from every source."""
    merged = _merged_for_display()
    return _index_from_meta(merged.vr, merged)


def load_demucs_catalog_display_index() -> Dict[str, str]:
    """Build Demucs stem→runtime-display index from every source."""
    merged = _merged_for_display()
    return _index_from_meta(merged.demucs, merged)
```

`_index_from_meta` maps **every** file including the `.yaml`, which is what lets Demucs resolve on its yaml stem the way `build_demucs_display_index` did. `setdefault` preserves upstream-wins.

- [ ] **Step 4: Keep the existing sanitizers — do NOT delete them**

The obvious cleanup here is wrong, and the sweep proves it:

```bash
rg -n "sanitize_catalogue_label|sanitize_vr_catalogue_label|sanitize_demucs_catalogue_label|build_checkpoint_display_index|build_vr_display_index|build_demucs_display_index" --type py
```

Live callers outside `model_display.py`:

| Caller | Uses |
| --- | --- |
| `core/ensemble_presets.py:155,158,163` | `sanitize_catalogue_label` for **casefolded matching** |
| `core/mdx_c_registry.py:16,20` | re-exports `build_checkpoint_display_index`, `sanitize_catalogue_label` |
| `scripts/generate_models_catalogue.py:25` | imports `sanitize_catalogue_label` *via* `mdx_c_registry` |
| `tests/test_mdx_c_registry.py:13,24` | both |

`ensemble_presets` compares sanitized labels to resolve a preset member to a
model. `canonical_display_name` **reformats** (inserts `—` and `·`); swapping it
in there would silently break preset resolution. The two functions have
genuinely different jobs: one strips for matching, one renders for display.

So: leave `sanitize_catalogue_label`, `sanitize_vr_catalogue_label`,
`sanitize_demucs_catalogue_label` and the three `build_*_display_index` helpers
in `core/model_display.py` untouched. They are no longer on the display path —
only `_index_from_meta` is — but they remain the matching utilities their other
callers need.

Note that `strip_catalogue_prefix` (Task 1) is a deliberate **superset** of
`sanitize_catalogue_label`: it also strips `VR Arch ` and `Apollo Model: `.
Do not unify them in this task. Changing what `ensemble_presets` matches on is a
separate change with its own test, and is out of scope here.

The only edit in this step: nothing. Confirm the module still imports cleanly.

Run: `.venv/bin/python -c "import core.model_display, core.ensemble_presets, core.mdx_c_registry; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_model_display tests.test_mdx_c_registry tests.test_generate_models_catalogue -v`
Expected: PASS, including the new regression class.

- [ ] **Step 6: Verify against real installed models**

```bash
.venv/bin/python -c "
import os, glob
from core.model_display import load_mdx_catalog_display_index
idx = load_mdx_catalog_display_index()
raw = []
for p in sorted(glob.glob('models/MDX_Net_Models/*.ckpt')) + sorted(glob.glob('models/MDX_Net_Models/*.onnx')):
    b = os.path.splitext(os.path.basename(p))[0]
    tag = 'OK  ' if b in idx else 'RAW '
    if b not in idx: raw.append(b)
    print(tag, b, '->', idx.get(b, ''))
print()
print('still raw:', raw)
"
```

Expected: `still raw: []`

- [ ] **Step 7: Commit**

```bash
git add core/model_display.py tests/test_model_display.py
git commit -m "fix(core): name mvsepless and extras models in runtime pickers"
```

---

### Task 6: Download Center presentation

**Files:**
- Modify: `ui/download_center.py:56-70` (`catalogue_matches`), `:366-407` (row builders), `:437-445` (`_apply_row_size`), `:732-758` (`_rebuild_catalogue`)
- Modify: `tests/test_download_center_search.py`

**Interfaces:**
- Consumes: `DownloadManager.catalogue_meta` / `EntryMeta` (Task 4), `sdr_for_files` / `primary_sdr` / `format_sdr_subtitle` (Task 2).
- Produces: no new public API. `_uvr_model_name` keeps holding the **raw catalogue label**.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_download_center_search.py`:

```python
class CanonicalSearchTests(unittest.TestCase):
    def test_query_matches_canonical_name(self) -> None:
        from ui.download_center import catalogue_matches

        names = ["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        # "MelBand" appears only in the canonical rendering, not the raw label.
        self.assertEqual(catalogue_matches(names, "MelBand"), names)

    def test_query_still_matches_raw_label(self) -> None:
        from ui.download_center import catalogue_matches

        names = ["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        self.assertEqual(catalogue_matches(names, "Mel-Band"), names)

    def test_non_matching_query_filtered_out(self) -> None:
        from ui.download_center import catalogue_matches

        names = ["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        self.assertEqual(catalogue_matches(names, "demucs"), [])


class RowSubtitleTests(unittest.TestCase):
    def test_scored_model_names_its_stem(self) -> None:
        from core.model_scores import format_sdr_subtitle

        self.assertEqual(
            format_sdr_subtitle(10.94, "1.2 GB", stem="vocals"),
            "vocals 10.9 SDR · 1.2 GB",
        )

    def test_unscored_model_falls_back_to_stems(self) -> None:
        from core.model_scores import format_sdr_subtitle

        self.assertEqual(
            format_sdr_subtitle(None, "890 MB", extra="vocals, other"),
            "vocals, other · 890 MB",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_download_center_search -v`
Expected: FAIL on `test_query_matches_canonical_name` — `[] != ['Roformer Model: ...']`

- [ ] **Step 3: Make search cover canonical names**

In `ui/download_center.py`, replace `catalogue_matches` (lines 56-70):

```python
def catalogue_matches(
    names: list[str],
    query: str,
    *,
    purpose: str = PURPOSE_ALL,
) -> list[str]:
    """Return selectable catalogue names matching query and purpose filter.

    Matching covers both the raw catalogue label and its canonical rendering,
    so a user typing what the row *shows* finds it.
    """
    selectable = [
        name for name in names if name not in (NO_NEW_MODELS, NO_CONNECTION)
    ]
    selectable = filter_labels_by_purpose(selectable, purpose)
    folded = query.strip().casefold()
    if not folded:
        return selectable
    return [
        name
        for name in selectable
        if folded in name.casefold()
        or folded in canonical_display_name(name).casefold()
    ]
```

Add to the imports at the top of the file:

```python
from core.model_naming import canonical_display_name
from core.model_scores import primary_sdr, sdr_for_files
```

- [ ] **Step 4: Build rows with canonical titles and the fallback subtitle**

Replace `_add_model_row` (lines 366-390):

```python
    def _row_score(self, name: str) -> tuple[str | None, float | None, str]:
        """Return ``(stem, sdr, stems_text)`` for a catalogue label.

        Falls back to the filename regex when the benchmark table has no entry,
        which covers the handful of models whose SDR lives only in their name.
        """
        meta = self.manager.catalogue_meta.get(name)
        stems_text = ", ".join(meta.stems) if meta and meta.stems else ""
        if meta is not None:
            # CROSS-PLAN: stem_count disambiguates a 2-stem 'other' (meaning
            # instrumental) from a 4-stem model's real 'other' residual.
            scored = primary_sdr(
                sdr_for_files(meta.files),
                meta.target_instrument,
                stem_count=len(meta.stems) or 2,
            )
            if scored is not None:
                return (scored[0], scored[1], stems_text)
        return (None, parse_sdr_score(name), stems_text)

    def _add_model_row(self, arch: str, name: str) -> None:
        if name in (NO_NEW_MODELS, NO_CONNECTION):
            return
        key = (arch, name)
        if key in self._row_checks or key in self._row_actions:
            return

        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        check.connect("toggled", lambda *_: self._on_row_check_toggled(key))

        stem, sdr, stems_text = self._row_score(name)

        action = Adw.ActionRow()
        set_row_title(action, canonical_display_name(name))
        action.add_prefix(check)
        action.set_activatable_widget(check)
        # Identity stays the raw catalogue label: resolve()/download() key on it.
        action._uvr_model_name = name  # type: ignore[attr-defined]
        action._uvr_check = check  # type: ignore[attr-defined]
        action._uvr_unsupported = False  # type: ignore[attr-defined]
        action._uvr_sdr = sdr  # type: ignore[attr-defined]
        action._uvr_sdr_stem = stem  # type: ignore[attr-defined]
        action._uvr_stems_text = stems_text  # type: ignore[attr-defined]
        set_row_subtitle(action, format_sdr_subtitle(sdr, stem=stem, extra=stems_text))

        self._row_checks[key] = check
        self._row_actions[key] = action
        self._list_boxes[arch].append(action)
```

In `_add_unsupported_row` (lines 392-407), change the title only — the "Unsupported — reason" subtitle stays:

```python
        set_row_title(action, canonical_display_name(name))
```

and set the two new attributes so the shared handlers never hit a missing one:

```python
        action._uvr_sdr = parse_sdr_score(name)  # type: ignore[attr-defined]
        action._uvr_sdr_stem = None  # type: ignore[attr-defined]
        action._uvr_stems_text = ""  # type: ignore[attr-defined]
```

- [ ] **Step 5: Carry stem and stems-text through the size handlers**

In `_on_row_check_toggled` (line 419) and `_apply_row_size` (line 444), replace both `set_row_subtitle(...)` calls with:

```python
            set_row_subtitle(
                action,
                format_sdr_subtitle(
                    getattr(action, "_uvr_sdr", None),
                    text or "",
                    stem=getattr(action, "_uvr_sdr_stem", None),
                    extra=getattr(action, "_uvr_stems_text", ""),
                ),
            )
```

In `_on_row_check_toggled` the size argument is `""` rather than `text or ""` — it restores the no-size subtitle.

- [ ] **Step 6: Sort by the real score**

In `_rebuild_catalogue` (lines 741-744), replace the sort branch:

```python
            if self._sort_mode == SORT_SDR:
                def _sort_key(label: str) -> tuple[int, float, str]:
                    _stem, sdr, _stems = self._row_score(label)
                    if sdr is None:
                        return (1, 0.0, canonical_display_name(label).casefold())
                    return (0, -sdr, canonical_display_name(label).casefold())

                models = sorted(models, key=_sort_key)
            else:
                models = sorted(
                    models, key=lambda value: canonical_display_name(value).casefold()
                )
```

Unscored models keep the tail position `sort_labels_by_sdr` already gave them. `sort_labels_by_sdr` stays exported for its own unit tests but is no longer called here — leave it in place.

- [ ] **Step 7: Run the UI tests**

Run: `.venv/bin/python -m unittest tests.test_download_center_search tests.test_download_center_state tests.test_download_chip_debug -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add ui/download_center.py tests/test_download_center_search.py
git commit -m "feat(ui): canonical names and real SDR badges in Download Center"
```

---

### Task 7: Full verification

**Files:** none modified unless a failure is found.

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS, no errors. Skips are acceptable only for the GTK-guarded and network-guarded classes.

- [ ] **Step 2: Type check**

Run: `.venv/bin/python -m pyright`
Expected: 0 errors. `models/` and `vendor/demucs` stay excluded — do not chase errors there.

- [ ] **Step 3: Confirm the reported bug is gone end to end**

```bash
.venv/bin/python -c "
import os, glob
from core.model_display import load_mdx_catalog_display_index
idx = load_mdx_catalog_display_index()
raw = [os.path.splitext(os.path.basename(p))[0]
       for p in glob.glob('models/MDX_Net_Models/*.ckpt') + glob.glob('models/MDX_Net_Models/*.onnx')
       if os.path.splitext(os.path.basename(p))[0] not in idx]
print('still raw:', raw)
assert not raw, raw
print('OK')
"
```

Expected: `still raw: []` then `OK`

- [ ] **Step 4: Measure the SDR coverage improvement**

```bash
.venv/bin/python -c "
from core.downloads import DownloadManager
from core.model_scores import sdr_for_files, primary_sdr
dm = DownloadManager(); dm.ensure_catalogues()
total = scored = 0
for cat in (dm.vr_download_list, dm.mdx_download_list, dm.demucs_download_list, dm.apollo_download_list):
    for label in cat:
        total += 1
        meta = dm.catalogue_meta.get(label)
        if meta and primary_sdr(sdr_for_files(meta.files), meta.target_instrument,
                                stem_count=len(meta.stems) or 2):
            scored += 1
print(f'scored {scored}/{total} = {100*scored/total:.1f}%  (was 2.0%)')
"
```

Expected: `scored 71/461 = 15.4%`, broken down `vr 21/28, mdx 46/407, demucs 4/24, apollo 0/2`.

**Not 98/461.** The source audit counted entries whose filename *matches* a
score key; 98 is correct for that. But 27 of those matches aggregate to an
empty stem dict, because 28 entries in the score table carry no track scores
at all — De-Echo, DeNoise, DeReverb, Wind Inst, Reverb HQ, Crowd HQ, MDX23C
DrumSep and friends. Utility and effects models have nothing meaningful to
benchmark on a vocals/instrumental test set. 71 is the number of rows that
will actually show a badge.

A materially lower number than 71 means the `.yaml` lookup or the aggregation
is dropping matches — investigate before proceeding.

- [ ] **Step 5: Launch and eyeball the Download Center**

Run: `./run_uvr.sh`, open Download Center, confirm: no `Roformer Model: ` prefixes, subtitles show either `<stem> N.N SDR · <size>` or `<stems> · <size>`, and Sort by SDR puts scored models first. Then open Separation and confirm the MDX model dropdown shows no raw basenames.

- [ ] **Step 6: Final commit**

```bash
git add -u
git commit -m "test: verify catalogue naming and score unification"
```

---

## Self-Review Notes

**Spec coverage:** `catalog_sources` → Task 4; `model_naming` → Task 1; score backend with the `seconds_per_minute_m3` exclusion, `.yaml` lookup and zero-track handling → Task 2; mvsepless metadata retention and the Russian category table → Task 3; the raw-basename fix with its regression test → Task 5; subtitle fallback chain, stem-labelled badge and target-stem sort → Task 6; full verification → Task 7. No spec section is unimplemented.

**Interface consistency:** `sdr_for_files(filenames, scores=None)`, `primary_sdr(stem_scores, target_stem=None)` and `format_sdr_subtitle(sdr, size_text="", *, stem=None, extra="")` are defined in Task 2 and called with those exact signatures in Task 6. `EntryMeta.files` / `.stems` / `.target_instrument` are defined in Task 4 and read in Tasks 5 and 6. `canonical_display_name` is defined in Task 1 and used in Tasks 4, 5 and 6.

**Correction made during review:** Task 5 Step 4 originally deleted the three
`sanitize_*` helpers and the three `build_*_display_index` helpers. The `rg`
sweep showed live callers in `core/ensemble_presets.py`,
`core/mdx_c_registry.py`, `scripts/generate_models_catalogue.py` and
`tests/test_mdx_c_registry.py`. `ensemble_presets` uses
`sanitize_catalogue_label` for casefolded **matching**, where
`canonical_display_name`'s reformatting would break preset resolution. The step
now explicitly keeps them and says why.

**Known risk:** `strip_catalogue_prefix` is a superset of
`sanitize_catalogue_label` (it also strips `VR Arch ` and `Apollo Model: `).
Both now exist. Unifying them means changing what `ensemble_presets` matches on
and belongs in its own change with its own test — explicitly out of scope.

**Corrections made during the fine-tuning pass:**

1. **Task 4's merge-order test patched away the merge it was testing.**
   `_supplemental_sources` took the base catalogues and returned them already
   merged, so substituting it in a test replaced the upstream-wins logic under
   assertion — the test would have failed, or worse, passed vacuously. It now
   takes no arguments and returns the supplements alone; `merged_catalogues`
   performs the base merge in one place. Two tests added to cover base and
   supplement surviving together, and the VR plain-string entry shape.
2. **`canonical_display_name` was not idempotent, and dropped families.**
   Prototyped against all 461 real catalogue entries, which surfaced two bugs
   the dialect table missed: re-running it stripped the `·` author separator
   (the author regex matched only `by X`), and for families
   `canonical_family` cannot re-detect — MDX-Net, Demucs `vN` — a second pass
   also ate the `—`. Separately, `SCnet: 4-stems Huge SCNet Bleedless` lost its
   family entirely, because the prefix was the only place it was named. Fixed
   with `split_catalogue_prefix` returning the prefix's family, an
   already-canonical short-circuit, and an author regex accepting both
   separators. The committed version is the prototyped one: 461/461
   idempotent, none emptied. Task 1 Step 5 runs that sweep.
3. **`catalogue_meta_for_label` was a module global written as a side effect of
   the last merge.** Every reader silently depended on someone having called
   the merge first, and returned "no metadata" rather than failing when they
   had not. Removed; metadata now travels on `DownloadManager.catalogue_meta`,
   which the Download Center already holds a reference to.

**Deliberately unchanged:** `sort_labels_by_sdr` stays exported and tested but
is no longer called by `_rebuild_catalogue`, which needs per-entry file lookup
that a label-only sort cannot do.
