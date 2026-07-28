# Model Options Sheet Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the global model-options sheet into a compact, capped-width dialog whose tabs show live section state, move the misplaced global vocal-splitter settings onto the pages that run separations, and hide secondary-model stem slots that cannot affect the run.

**Architecture:** Three independent layers. A new pure module (`ui/option_summaries.py`) turns settings into one-line state strings and applicability booleans — no GTK, fully testable headlessly. A new self-contained widget (`ui/widgets/vocal_split_row.py`) owns its own settings binding, modelled on the existing `OutputFormatRow`, and is dropped into the Processing group on the Separation and Ensemble pages. The sheet itself (`ui/model_options/sheet.py`) loses its parent-width tracking, gains a 760px cap and non-homogeneous columns, and replaces two ad-hoc `Gtk.Label` mechanisms with `Adw.Banner` plus `Adw.ViewStackPage` badge numbers.

**Tech Stack:** Python 3, PyGObject, GTK 4, libadwaita 1.9.2, stdlib `unittest`.

## Global Constraints

- **No tkinter anywhere.** `core/` must stay framework-agnostic; never import from `ui/` into `core/`.
- **Settings are one flat dict.** This plan introduces **no new settings keys**. Every key used already exists in `bundled/constants/defaults.py`.
- **GTK only on the main loop.** No engine/worker code touches widgets.
- **Search with `rg`**, never `grep` or `git grep`.
- **Tests are stdlib `unittest`.** There is no pytest config. Run with `.venv/bin/python -m unittest ...`.
- **GTK-dependent tests** guard with `@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), ...)` and do `gi.require_version("Gtk", "4.0")` / `("Adw", "1")` inside `setUpClass`, registering an `Adw.Application` with a **unique** `application_id`.
- **Upstream's `Seperate*` misspelling stays.** Do not "fix" it.
- **Commit messages end with:** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- **Push to `origin` (Codeberg) only.** Never push to the `github` remote. This plan does not push at all.
- Full test suite must stay green: `.venv/bin/python -m unittest discover -s tests -v` (694 tests at plan time).

## Spec

Design spec: [docs/superpowers/specs/2026-07-27-model-options-sheet-design.md](../specs/2026-07-27-model-options-sheet-design.md)

## Execution order

**Tasks run 1 → 2 → 3 → 4 → 5 → 6 → 8 → 7 → 9.** Task 8 before Task 7 is
deliberate, not a typo.

Task 7 renames `applicability_subtitle` to `applicability_banner`, and
`ui/model_options/sheet.py` imports and calls the old name. If Task 7 ran first
it would have to leave a shim writing into `_tab_subtitles` — a label Task 8 is
about to delete — so one commit would ship code written only to be removed.
Running Task 8 first deletes the subtitle rendering and its import outright,
leaving Task 7 free to rename a function nothing references.

Task numbering is unchanged so the dependency notes in each task still line up.

## File Structure

| File | Responsibility |
|---|---|
| `ui/option_summaries.py` | **New.** Pure functions: settings → section subtitle strings, and the four-stem-slot applicability rule. No GTK import. |
| `ui/widgets/vocal_split_row.py` | **New.** `VocalSplitRow(Adw.ExpanderRow)` — the five global vocal-split/deverb settings with self-owned `apply_from_settings` / `persist_to_settings`. |
| `ui/views/base.py` | Drops the vocal-split section; gains `maintenance_group`, secondary stem-slot visibility, and expander subtitles + auto-expand. |
| `ui/window.py` | Hosts `VocalSplitRow` in the Separation Processing group; supplies `on_switch_method` to the sheet. |
| `ui/ensemble/window.py` | Hosts `VocalSplitRow` in the Ensemble Processing group. |
| `ui/model_options/applicability.py` | `applicability_banner` replaces `applicability_subtitle`. |
| `ui/model_options/__init__.py` | Export update. |
| `ui/model_options/sheet.py` | Dialog shell: width cap, content-height, non-homogeneous columns, banners, badges. |

---

### Task 1: Pure option summaries

**Files:**
- Create: `ui/option_summaries.py`
- Test: `tests/test_option_summaries.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `OFF: str` = `"Off"`
  - `ON_NO_MODEL: str` = `"On — no model selected"`
  - `four_stem_secondaries_apply(settings, process_method: str) -> bool`
  - `secondary_models_summary(settings, prefix: str, *, four_stem: bool) -> str`
  - `preproc_summary(settings) -> str`
  - `vocal_split_summary(settings) -> str`

  `settings` is anything with a `.get(key, default=None)` method — `SettingsModel` in production, a plain dict wrapper in tests. `prefix` is `"vr"`, `"mdx"` or `"demucs"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_summaries.py`:

```python
"""Pure settings-to-subtitle summaries for collapsible option sections."""

from __future__ import annotations

import unittest

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    FOUR_STEM_ENSEMBLE,
    MDX_ARCH_TYPE,
    MULTI_STEM_ENSEMBLE,
    NO_MODEL,
)
from ui.option_summaries import (
    OFF,
    ON_NO_MODEL,
    four_stem_secondaries_apply,
    preproc_summary,
    secondary_models_summary,
    vocal_split_summary,
)


class _Settings:
    """Minimal stand-in for SettingsModel: a dict with .get(key, default)."""

    def __init__(self, **values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


class FourStemApplicabilityTests(unittest.TestCase):
    def test_demucs_with_all_stems_uses_four_slots(self):
        settings = _Settings(demucs_stems=ALL_STEMS)
        self.assertTrue(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))

    def test_demucs_without_all_stems_does_not(self):
        settings = _Settings(demucs_stems="Vocals")
        self.assertFalse(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))

    def test_mdx_alone_never_uses_four_slots(self):
        settings = _Settings(demucs_stems=ALL_STEMS)
        self.assertFalse(four_stem_secondaries_apply(settings, MDX_ARCH_TYPE))

    def test_four_stem_ensemble_applies_to_every_architecture(self):
        settings = _Settings(
            chosen_process_method=ENSEMBLE_MODE,
            ensemble_main_stem=FOUR_STEM_ENSEMBLE,
        )
        self.assertTrue(four_stem_secondaries_apply(settings, MDX_ARCH_TYPE))
        self.assertTrue(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))

    def test_multi_stem_ensemble_applies_to_demucs_only(self):
        settings = _Settings(
            chosen_process_method=ENSEMBLE_MODE,
            ensemble_main_stem=MULTI_STEM_ENSEMBLE,
        )
        self.assertTrue(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))
        self.assertFalse(four_stem_secondaries_apply(settings, MDX_ARCH_TYPE))


class SecondaryModelsSummaryTests(unittest.TestCase):
    def test_off_when_not_activated(self):
        settings = _Settings(mdx_is_secondary_model_activate=False)
        self.assertEqual(
            secondary_models_summary(settings, "mdx", four_stem=False), OFF
        )

    def test_on_but_unset_reports_no_model(self):
        settings = _Settings(
            mdx_is_secondary_model_activate=True,
            mdx_voc_inst_secondary_model=NO_MODEL,
        )
        self.assertEqual(
            secondary_models_summary(settings, "mdx", four_stem=False), ON_NO_MODEL
        )

    def test_describes_the_configured_pair(self):
        settings = _Settings(
            mdx_is_secondary_model_activate=True,
            mdx_voc_inst_secondary_model="MDX-Net: UVR-MDX-NET Inst HQ 3",
            mdx_voc_inst_secondary_model_scale=0.9,
        )
        summary = secondary_models_summary(settings, "mdx", four_stem=False)
        self.assertIn("UVR-MDX-NET Inst HQ 3", summary)
        self.assertIn("0.90", summary)
        self.assertNotIn("MDX-Net:", summary)

    def test_two_stem_ignores_other_bass_drums(self):
        settings = _Settings(
            demucs_is_secondary_model_activate=True,
            demucs_voc_inst_secondary_model=NO_MODEL,
            demucs_bass_secondary_model="VR Arc: 1_HP-UVR",
            demucs_bass_secondary_model_scale=0.5,
        )
        self.assertEqual(
            secondary_models_summary(settings, "demucs", four_stem=False), ON_NO_MODEL
        )

    def test_four_stem_includes_other_bass_drums(self):
        settings = _Settings(
            demucs_is_secondary_model_activate=True,
            demucs_voc_inst_secondary_model=NO_MODEL,
            demucs_bass_secondary_model="VR Arc: 1_HP-UVR",
            demucs_bass_secondary_model_scale=0.5,
        )
        summary = secondary_models_summary(settings, "demucs", four_stem=True)
        self.assertIn("1_HP-UVR", summary)

    def test_multiple_pairs_are_joined(self):
        settings = _Settings(
            demucs_is_secondary_model_activate=True,
            demucs_voc_inst_secondary_model="MDX-Net: A",
            demucs_voc_inst_secondary_model_scale=0.9,
            demucs_bass_secondary_model="VR Arc: B",
            demucs_bass_secondary_model_scale=0.5,
        )
        summary = secondary_models_summary(settings, "demucs", four_stem=True)
        self.assertIn(" · ", summary)


class PreprocSummaryTests(unittest.TestCase):
    def test_off_when_not_activated(self):
        self.assertEqual(
            preproc_summary(_Settings(is_demucs_pre_proc_model_activate=False)), OFF
        )

    def test_on_but_unset_reports_no_model(self):
        settings = _Settings(
            is_demucs_pre_proc_model_activate=True,
            demucs_pre_proc_model=NO_MODEL,
        )
        self.assertEqual(preproc_summary(settings), ON_NO_MODEL)

    def test_names_the_model(self):
        settings = _Settings(
            is_demucs_pre_proc_model_activate=True,
            demucs_pre_proc_model="MDX-Net: UVR-MDX-NET Inst HQ 3",
        )
        self.assertEqual(preproc_summary(settings), "UVR-MDX-NET Inst HQ 3")

    def test_mentions_the_instrumental_mixture(self):
        settings = _Settings(
            is_demucs_pre_proc_model_activate=True,
            demucs_pre_proc_model="MDX-Net: X",
            is_demucs_pre_proc_model_inst_mix=True,
        )
        self.assertIn("instrumental mixture", preproc_summary(settings))


class VocalSplitSummaryTests(unittest.TestCase):
    def test_off_only_when_both_switches_are_off(self):
        settings = _Settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        self.assertEqual(vocal_split_summary(settings), OFF)

    def test_splitter_alone_names_the_model(self):
        settings = _Settings(
            is_set_vocal_splitter=True,
            set_vocal_splitter="VR Arc: UVR-BVE-4B",
            is_deverb_vocals=False,
        )
        self.assertEqual(vocal_split_summary(settings), "UVR-BVE-4B")

    def test_splitter_on_without_model_reports_no_model(self):
        settings = _Settings(
            is_set_vocal_splitter=True,
            set_vocal_splitter=NO_MODEL,
            is_deverb_vocals=False,
        )
        self.assertEqual(vocal_split_summary(settings), ON_NO_MODEL)

    def test_deverb_alone_is_described_without_a_splitter(self):
        settings = _Settings(
            is_set_vocal_splitter=False,
            is_deverb_vocals=True,
            deverb_vocal_opt="Main Vocals Only",
        )
        self.assertEqual(vocal_split_summary(settings), "deverb: Main Vocals Only")

    def test_both_are_joined(self):
        settings = _Settings(
            is_set_vocal_splitter=True,
            set_vocal_splitter="VR Arc: UVR-BVE-4B",
            is_deverb_vocals=True,
            deverb_vocal_opt="All Vocal Types",
        )
        self.assertEqual(
            vocal_split_summary(settings), "UVR-BVE-4B · deverb: All Vocal Types"
        )

    def test_missing_keys_degrade_to_off(self):
        self.assertEqual(vocal_split_summary(_Settings()), OFF)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_option_summaries -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'ui.option_summaries'`.

- [ ] **Step 3: Confirm the constant names exist**

Run:

```bash
rg -n "^ALL_STEMS|^FOUR_STEM_ENSEMBLE|^MULTI_STEM_ENSEMBLE|^ENSEMBLE_MODE|^NO_MODEL|^VOCAL_PAIR|^OTHER_PAIR|^BASS_PAIR|^DRUM_PAIR|^CHOOSE_STEM_PAIR" bundled/constants/*.py
```

Every name in that list must resolve. If any does not, find its real spelling with `rg` before writing the module — do not invent one.

- [ ] **Step 4: Write the implementation**

Create `ui/option_summaries.py`:

```python
"""Pure state summaries for collapsible option sections.

Each function turns a settings mapping into the one-line subtitle shown on a
collapsed ``Adw.ExpanderRow``, so a user can see whether a section is on, and
what it will do, without opening it.

No GTK import: these are plain functions over ``settings.get`` and are unit
tested headlessly. They live at the ``ui/`` root rather than under
``ui/model_options/`` because both :mod:`ui.views.base` and
:mod:`ui.widgets.vocal_split_row` consume them, and a widget importing from
``model_options`` would invert the dependency.
"""

from __future__ import annotations

from typing import List, Tuple

from bundled.constants import (
    ALL_STEMS,
    BASS_PAIR,
    CHOOSE_STEM_PAIR,
    DEMUCS_ARCH_TYPE,
    DRUM_PAIR,
    ENSEMBLE_MODE,
    ENSEMBLE_PARTITION,
    FOUR_STEM_ENSEMBLE,
    MULTI_STEM_ENSEMBLE,
    NO_MODEL,
    OTHER_PAIR,
    VOCAL_PAIR,
)

#: Subtitle for a section whose every activate switch is off.
OFF = "Off"
#: Subtitle for a section that is on but has no model chosen yet.
ON_NO_MODEL = "On — no model selected"

#: Joins the parts of a multi-part summary.
_SEP = " · "

#: ``(slot, label)`` for the secondary-model stem pairs, matching the order of
#: ``ui.views.base._SECONDARY_SLOTS``. Only the first entry applies unless the
#: run uses four sources -- see :func:`four_stem_secondaries_apply`.
_SECONDARY_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("voc_inst", VOCAL_PAIR),
    ("other", OTHER_PAIR),
    ("bass", BASS_PAIR),
    ("drums", DRUM_PAIR),
)


def _model_label(tag) -> str:
    """Strip the ``"<arch>: "`` prefix from a stored model tag.

    Stored values come from ``ModelData.model_and_process_tag`` (e.g.
    ``"MDX-Net: UVR-MDX-NET Inst HQ 3"``). Subtitles are tight on space and the
    architecture is already implied by the tab, so only the model name is kept.
    Returns ``""`` for an unset model, which callers treat as "not configured".
    """
    if not tag or tag == NO_MODEL:
        return ""
    text = str(tag)
    _, separator, name = text.partition(ENSEMBLE_PARTITION)
    return name if separator else text


def four_stem_secondaries_apply(settings, process_method: str) -> bool:
    """Whether the ``other`` / ``bass`` / ``drums`` secondary slots can affect a run.

    Mirrors the engine's own branch in ``core/model_data.py`` (the
    ``is_valid_ensemble or is_4_stem_ensemble or is_multi_stem_ensemble_demucs``
    condition): the four-slot path runs for a Demucs model exporting all stems,
    for any member of a 4-stem ensemble, and for a Demucs member of a multi-stem
    ensemble. In every other case those three slots are dead weight.
    """
    is_demucs = process_method == DEMUCS_ARCH_TYPE
    if settings.get("chosen_process_method") == ENSEMBLE_MODE:
        main_stem = settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        if main_stem == FOUR_STEM_ENSEMBLE:
            return True
        if main_stem == MULTI_STEM_ENSEMBLE and is_demucs:
            return True
    return is_demucs and settings.get("demucs_stems") == ALL_STEMS


def secondary_models_summary(settings, prefix: str, *, four_stem: bool) -> str:
    """One-line state of the per-architecture secondary-model section.

    ``four_stem`` must match what the section actually shows (see
    :func:`four_stem_secondaries_apply`) so the subtitle never describes a slot
    the user cannot see.
    """
    if not settings.get(f"{prefix}_is_secondary_model_activate"):
        return OFF

    pairs = _SECONDARY_PAIRS if four_stem else _SECONDARY_PAIRS[:1]
    parts: List[str] = []
    for slot, label in pairs:
        name = _model_label(settings.get(f"{prefix}_{slot}_secondary_model", NO_MODEL))
        if not name:
            continue
        scale = settings.get(f"{prefix}_{slot}_secondary_model_scale", 0.9)
        try:
            scale_text = f"{float(scale):.2f}"
        except (TypeError, ValueError):
            scale_text = str(scale)
        parts.append(f"{label}: {name} ({scale_text})")

    return _SEP.join(parts) if parts else ON_NO_MODEL


def preproc_summary(settings) -> str:
    """One-line state of the Demucs pre-process-model section."""
    if not settings.get("is_demucs_pre_proc_model_activate"):
        return OFF
    name = _model_label(settings.get("demucs_pre_proc_model", NO_MODEL))
    if not name:
        return ON_NO_MODEL
    if settings.get("is_demucs_pre_proc_model_inst_mix"):
        return f"{name}{_SEP}saves instrumental mixture"
    return name


def vocal_split_summary(settings) -> str:
    """One-line state of the vocal-splitter and deverb section.

    This section holds two independent switches, so it is ``OFF`` only when both
    are off; otherwise the enabled halves are joined.
    """
    split_on = bool(settings.get("is_set_vocal_splitter"))
    deverb_on = bool(settings.get("is_deverb_vocals"))
    if not split_on and not deverb_on:
        return OFF

    parts: List[str] = []
    if split_on:
        name = _model_label(settings.get("set_vocal_splitter", NO_MODEL))
        parts.append(name if name else ON_NO_MODEL)
    if deverb_on:
        parts.append(f"deverb: {settings.get('deverb_vocal_opt', 'Main Vocals Only')}")
    return _SEP.join(parts)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_option_summaries -v`

Expected: PASS, 20 tests.

If `ENSEMBLE_PARTITION` is not `": "`, the `_model_label` tests will fail — check its real value with `rg -n "ENSEMBLE_PARTITION" bundled/constants/` and fix the test fixtures' tag strings to match, not the implementation.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5`

Expected: OK, 714 tests (694 + 20).

- [ ] **Step 7: Commit**

```bash
git add ui/option_summaries.py tests/test_option_summaries.py
git commit -m "feat(ui): add pure option-section state summaries

Turns settings into the one-line subtitles shown on collapsed option
expanders, plus the rule for when the other/bass/drums secondary slots
can actually affect a run (mirrors core/model_data.py's own branch).

No GTK import, so the whole module is testable without a display.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `VocalSplitRow` widget

**Files:**
- Create: `ui/widgets/vocal_split_row.py`
- Test: `tests/test_vocal_split_row.py`

**Interfaces:**
- Consumes: `ui.option_summaries.vocal_split_summary`, `OFF` (Task 1).
- Produces:
  - `class VocalSplitRow(Adw.ExpanderRow)`
  - `VocalSplitRow(repo, on_changed, hints=None)` — `repo` is a `ModelRepository` (used only for `karaoke_model_list`), `on_changed` is a zero-argument callable, `hints` is an optional hint manager with a `.register(row, text)` method.
  - `.apply_from_settings(settings) -> None`
  - `.persist_to_settings(settings) -> None`
  - `.refresh_summary() -> None`
  - Public row attributes: `.split_switch`, `.splitter_row`, `.save_inst_switch`, `.deverb_switch`, `.deverb_row`

  Mirrors `ui.widgets.format_row.OutputFormatRow`'s contract so both windows call it from the same places.

- [ ] **Step 1: Read the widget it is modelled on**

Read [ui/widgets/format_row.py](../../../ui/widgets/format_row.py) in full. `VocalSplitRow` copies its shape: a `_syncing` guard around programmatic updates, a cached `self._settings` from the last `apply_from_settings`, and the `apply_from_settings` / `persist_to_settings` pair. Do not invent a different pattern.

Also read [ui/views/base.py:717-734](../../../ui/views/base.py#L717-L734) — the section being replaced. The new widget must keep the same five rows, the same order, the same titles, and the same two dependency-dimming relationships.

- [ ] **Step 2: Write the failing test**

Create `tests/test_vocal_split_row.py`:

```python
"""Vocal splitter + deverb row (global settings, hosted on the run pages)."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class VocalSplitRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.vocal-split-row")
        cls._app.register()

    def _settings(self, **overrides):
        from core.settings import SettingsModel

        settings = SettingsModel()
        for key, value in overrides.items():
            settings.set(key, value)
        return settings

    def _row(self):
        from ui.widgets.vocal_split_row import VocalSplitRow

        class _Repo:
            def karaoke_model_list(self, _settings):
                return ["VR Arc: UVR-BVE-4B"]

        self.changed = 0

        def on_changed():
            self.changed += 1

        return VocalSplitRow(_Repo(), on_changed)

    def test_applies_stored_switches(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=True, is_deverb_vocals=True)
        )
        self.assertTrue(row.split_switch.get_active())
        self.assertTrue(row.deverb_switch.get_active())

    def test_applying_settings_does_not_fire_on_changed(self):
        row = self._row()
        row.apply_from_settings(self._settings(is_set_vocal_splitter=True))
        self.assertEqual(self.changed, 0)

    def test_auto_expands_when_either_switch_is_on(self):
        row = self._row()
        row.apply_from_settings(self._settings(is_deverb_vocals=True))
        self.assertTrue(row.get_expanded())

    def test_stays_collapsed_when_both_switches_are_off(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertFalse(row.get_expanded())

    def test_never_auto_collapses_a_manually_opened_section(self):
        row = self._row()
        row.set_expanded(True)
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertTrue(row.get_expanded())

    def test_subtitle_reports_off_when_both_are_off(self):
        from ui.option_summaries import OFF

        row = self._row()
        row.apply_from_settings(self._settings(is_set_vocal_splitter=False))
        self.assertEqual(row.get_subtitle(), OFF)

    def test_subtitle_follows_a_switch_toggle(self):
        from ui.option_summaries import OFF

        row = self._row()
        row.apply_from_settings(self._settings(is_deverb_vocals=False))
        self.assertEqual(row.get_subtitle(), OFF)
        row.deverb_switch.set_active(True)
        self.assertIn("deverb", row.get_subtitle())

    def test_toggling_a_switch_fires_on_changed(self):
        row = self._row()
        row.apply_from_settings(self._settings())
        row.deverb_switch.set_active(True)
        self.assertGreaterEqual(self.changed, 1)

    def test_persist_writes_every_global_key(self):
        settings = self._settings()
        row = self._row()
        row.apply_from_settings(settings)
        row.split_switch.set_active(True)
        row.save_inst_switch.set_active(True)
        row.deverb_switch.set_active(True)
        row.persist_to_settings(settings)
        self.assertTrue(settings.get("is_set_vocal_splitter"))
        self.assertTrue(settings.get("is_save_inst_set_vocal_splitter"))
        self.assertTrue(settings.get("is_deverb_vocals"))
        self.assertIsNotNone(settings.get("deverb_vocal_opt"))

    def test_persist_does_not_clobber_an_unloaded_model_list(self):
        """Before the karaoke list is populated the stored tag must survive."""
        settings = self._settings(set_vocal_splitter="VR Arc: UVR-BVE-4B")
        row = self._row()
        row.apply_from_settings(settings)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("set_vocal_splitter"), "VR Arc: UVR-BVE-4B")

    def test_dependent_rows_are_dimmed_while_their_switch_is_off(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertFalse(row.splitter_row.get_sensitive())
        self.assertFalse(row.save_inst_switch.get_sensitive())
        self.assertFalse(row.deverb_row.get_sensitive())

    def test_dependent_rows_wake_up_with_their_switch(self):
        row = self._row()
        row.apply_from_settings(self._settings())
        row.split_switch.set_active(True)
        self.assertTrue(row.splitter_row.get_sensitive())
        self.assertTrue(row.save_inst_switch.get_sensitive())
        self.assertFalse(row.deverb_row.get_sensitive())

    def test_expanding_populates_the_splitter_model_list(self):
        from ui.widgets.rows import combo_values

        row = self._row()
        row.apply_from_settings(self._settings())
        row.set_expanded(True)
        self.assertIn("UVR-BVE-4B", " ".join(combo_values(row.splitter_row)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_vocal_split_row -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'ui.widgets.vocal_split_row'` (or SKIPPED with no display — if skipped, note it and continue; the suite still has to build the module for Task 3).

- [ ] **Step 4: Write the implementation**

Create `ui/widgets/vocal_split_row.py`:

```python
"""Vocal splitter + deverb section as a self-contained expander row.

These five settings -- ``is_set_vocal_splitter``, ``set_vocal_splitter``,
``is_save_inst_set_vocal_splitter``, ``is_deverb_vocals`` and
``deverb_vocal_opt`` -- are **unprefixed globals**. They used to be built once
per architecture view, so three copies edited one set of values and changing the
section on the VR tab silently changed MDX-Net and Demucs. They now live on the
pages that actually run separations (Separation and Ensemble), which both
consume the same globals, exactly as ``OutputFormatRow`` already does for
``save_format``.

The row owns its own settings binding rather than reusing ``MethodView``'s row
helpers: those register each row into per-view registries (``_option_rows``,
``_switch_rows``, ``_model_combos``) that ``MethodView.load`` / ``.save``
iterate, so they only work inside a view.
"""

from __future__ import annotations

from typing import Callable, Optional

from gi.repository import Adw

from bundled.constants import DEVERB_MAPPER, NO_MODEL

from ..help_text import (
    IS_DEVERB_OPT_HELP,
    IS_DEVERB_VOC_HELP,
    IS_VOC_SPLIT_INST_SAVE_SELECT_HELP,
    IS_VOC_SPLIT_MODEL_SELECT_HELP,
    VOC_SPLIT_MODEL_SELECT_HELP,
)
from ..option_summaries import OFF, vocal_split_summary
from .rows import (
    get_combo_value,
    make_combo_row,
    make_switch_row,
    set_combo_tag_values,
    set_combo_value,
    use_wrapping_list,
)

_DEFAULT_DEVERB = "Main Vocals Only"


class VocalSplitRow(Adw.ExpanderRow):
    """The five global vocal-split/deverb settings in one collapsible row."""

    def __init__(
        self,
        repo,
        on_changed: Callable[[], None],
        hints=None,
    ):
        super().__init__(title="Vocal splitter and deverb")
        self._repo = repo
        self._on_changed = on_changed
        #: Cached from the last ``apply_from_settings`` so interactive edits can
        #: write straight through and keep the subtitle in step. ``None`` until
        #: the row has been applied at least once.
        self._settings = None
        self._syncing = False
        #: The karaoke model list is expensive (it hashes checkpoints), so the
        #: combo starts seeded with just the stored tag and is filled on first
        #: expansion. Until then its value must not be written back, or an
        #: unopened row would clobber the stored tag with ``NO_MODEL``.
        self._models_ready = False
        self._stored_splitter = NO_MODEL

        self.split_switch = make_switch_row("Enable vocal split mode")
        self.splitter_row = make_combo_row("Vocal splitter model", [NO_MODEL])
        use_wrapping_list(self.splitter_row)
        self.save_inst_switch = make_switch_row("Save split vocal instrumentals")
        self.deverb_switch = make_switch_row("Deverb vocals")
        self.deverb_row = make_combo_row(
            "Deverb vocal type", list(DEVERB_MAPPER.keys())
        )

        for row in (
            self.split_switch,
            self.splitter_row,
            self.save_inst_switch,
            self.deverb_switch,
            self.deverb_row,
        ):
            self.add_row(row)

        if hints is not None:
            hints.register(self.split_switch, IS_VOC_SPLIT_MODEL_SELECT_HELP)
            hints.register(self.splitter_row, VOC_SPLIT_MODEL_SELECT_HELP)
            hints.register(self.save_inst_switch, IS_VOC_SPLIT_INST_SAVE_SELECT_HELP)
            hints.register(self.deverb_switch, IS_DEVERB_VOC_HELP)
            hints.register(self.deverb_row, IS_DEVERB_OPT_HELP)

        for row in (self.split_switch, self.save_inst_switch, self.deverb_switch):
            row.connect("notify::active", self._on_row_changed)
        for row in (self.splitter_row, self.deverb_row):
            row.connect("notify::selected", self._on_row_changed)
        self.connect("notify::expanded", self._populate_models)

        self.set_subtitle(OFF)
        self._sync_dependents()

    # -- Settings ---------------------------------------------------------------

    def apply_from_settings(self, settings) -> None:
        """Restore every row from ``settings`` without emitting changes."""
        self._settings = settings
        self._stored_splitter = settings.get("set_vocal_splitter", NO_MODEL) or NO_MODEL
        self._syncing = True
        try:
            self.split_switch.set_active(bool(settings.get("is_set_vocal_splitter")))
            self.save_inst_switch.set_active(
                bool(settings.get("is_save_inst_set_vocal_splitter"))
            )
            self.deverb_switch.set_active(bool(settings.get("is_deverb_vocals")))
            set_combo_value(
                self.deverb_row, settings.get("deverb_vocal_opt", _DEFAULT_DEVERB)
            )
            if not self._models_ready:
                seed = (
                    [NO_MODEL]
                    if self._stored_splitter == NO_MODEL
                    else [NO_MODEL, self._stored_splitter]
                )
                set_combo_tag_values(self.splitter_row, seed)
            set_combo_value(self.splitter_row, self._stored_splitter)
        finally:
            self._syncing = False

        self._sync_dependents()
        self.refresh_summary()
        # Expand only -- never auto-collapse, or a section the user opened by
        # hand would be shut on them by an unrelated settings reload.
        if self.split_switch.get_active() or self.deverb_switch.get_active():
            self.set_expanded(True)

    def persist_to_settings(self, settings) -> None:
        """Write every global vocal-split key back to ``settings``."""
        settings.set("is_set_vocal_splitter", self.split_switch.get_active())
        settings.set(
            "is_save_inst_set_vocal_splitter", self.save_inst_switch.get_active()
        )
        settings.set("is_deverb_vocals", self.deverb_switch.get_active())
        settings.set(
            "deverb_vocal_opt", get_combo_value(self.deverb_row) or _DEFAULT_DEVERB
        )
        # Only trust the combo once its real list has loaded; before that it is
        # a seeded placeholder and the stored tag is authoritative.
        if self._models_ready:
            settings.set("set_vocal_splitter", get_combo_value(self.splitter_row))
        else:
            settings.set("set_vocal_splitter", self._stored_splitter)

    def refresh_summary(self) -> None:
        """Re-read the section's subtitle from the cached settings."""
        settings = self._settings
        self.set_subtitle(vocal_split_summary(settings) if settings is not None else OFF)

    # -- Internals --------------------------------------------------------------

    def _sync_dependents(self) -> None:
        """Dim each activate switch's dependants while it is off.

        Matches ``MethodView._bind_switch_dependents``: an inapplicable control
        stays visible but non-interactive, so the section's shape never changes
        as switches flip.
        """
        split_on = self.split_switch.get_active()
        self.splitter_row.set_sensitive(split_on)
        self.save_inst_switch.set_sensitive(split_on)
        self.deverb_row.set_sensitive(self.deverb_switch.get_active())

    def _populate_models(self, *_args) -> None:
        if self._models_ready or not self.get_expanded():
            return
        self._models_ready = True
        try:
            values = self._repo.karaoke_model_list(self._settings)
        except Exception:
            values = []
        self._syncing = True
        try:
            set_combo_tag_values(self.splitter_row, [NO_MODEL, *values])
            set_combo_value(self.splitter_row, self._stored_splitter)
        finally:
            self._syncing = False

    def _on_row_changed(self, *_args) -> None:
        if self._syncing:
            return
        self._sync_dependents()
        if self._settings is not None:
            if self._models_ready:
                self._stored_splitter = (
                    get_combo_value(self.splitter_row) or NO_MODEL
                )
            self.persist_to_settings(self._settings)
            self.refresh_summary()
        self._on_changed()
```

- [ ] **Step 5: Verify the help-text constants exist**

Run:

```bash
rg -n "IS_VOC_SPLIT_MODEL_SELECT_HELP|VOC_SPLIT_MODEL_SELECT_HELP|IS_VOC_SPLIT_INST_SAVE_SELECT_HELP|IS_DEVERB_VOC_HELP|IS_DEVERB_OPT_HELP" ui/help_text.py
```

All five must exist (they are already imported by `ui/views/base.py`). If any lives elsewhere, follow `ui/views/base.py`'s own import for it rather than moving the constant.

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_vocal_split_row -v`

Expected: PASS, 13 tests (or all SKIPPED without a display).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5`

Expected: OK.

- [ ] **Step 8: Commit**

```bash
git add ui/widgets/vocal_split_row.py tests/test_vocal_split_row.py
git commit -m "feat(ui): add self-contained VocalSplitRow widget

The five vocal-split/deverb settings are unprefixed globals. This row owns
its own settings binding, mirroring OutputFormatRow, so it can live on the
Separation and Ensemble pages instead of being rebuilt per architecture.

Not wired up yet -- the swap lands in the next commit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Move the vocal-split section onto the run pages

**Files:**
- Modify: `ui/views/base.py` (delete lines 717-734, the `voc_split_expander` block)
- Modify: `ui/window.py:601-628` (`_build_shared_group`), `:684` (load), `:913` (flush)
- Modify: `ui/ensemble/window.py:366-370` (Processing group), `:446` (load), `:500-502` (change handler)
- Test: `tests/test_vocal_split_placement.py`

**Interfaces:**
- Consumes: `VocalSplitRow` (Task 2).
- Produces:
  - `MainWindow.vocal_split_row: VocalSplitRow`
  - `MainWindow._on_vocal_split_changed(*args) -> None`
  - `EnsemblePage.vocal_split_row: VocalSplitRow`
  - `EnsemblePage._on_vocal_split_changed(*args) -> None`
  - `MethodView` no longer has `voc_split_expander`.

**Facts already resolved — use these, do not re-derive:**
- The embedded ensemble page is class **`EnsemblePage`** (`ui/ensemble/window.py:132`), held by `MainWindow` as **`self._ensemble_page`** (`ui/window.py:368`). There is no `EnsembleWindow` class and no `ensemble_view` attribute.
- `MainWindow` has **no `_touch_settings` method.** Its `_on_format_changed` (`ui/window.py:852`) is simply `self.format_row.persist_to_settings(self.settings)`. Mirror that shape.
- `EnsemblePage` guards its handlers with `self._loading` and reaches the repo as `self.context.repo`.
- `MainWindow._hint_manager` is created at `ui/window.py:278`, before `_build_shared_group()` is called at `:341`, so passing `hints=self._hint_manager` from inside that builder is safe.

- [ ] **Step 1: Confirm nothing else references the old expander**

Run: `rg -n "voc_split_expander" ui/ tests/`

Expected: matches only inside `ui/views/base.py:717-734`. If anything else references it, stop and report — the deletion is not safe until those callers are handled.

- [ ] **Step 2: Write the failing test**

Create `tests/test_vocal_split_placement.py`:

```python
"""The vocal-split section lives on the run pages, not per-architecture."""

from __future__ import annotations

import os
import unittest


class MethodViewNoLongerOwnsItTests(unittest.TestCase):
    """Headless: the attribute is gone from the view class entirely."""

    def test_method_view_has_no_vocal_split_expander(self):
        from ui.views.base import MethodView

        self.assertFalse(hasattr(MethodView, "voc_split_expander"))

    def test_base_module_no_longer_builds_the_section(self):
        import inspect

        from ui.views import base

        source = inspect.getsource(base)
        self.assertNotIn("voc_split_expander", source)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ProcessingGroupPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.vocal-split-place")
        cls._app.register()

    def test_main_window_processing_group_hosts_the_row(self):
        from ui.widgets.vocal_split_row import VocalSplitRow
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        self.assertIsInstance(window.vocal_split_row, VocalSplitRow)

    def test_ensemble_page_processing_group_hosts_the_row(self):
        from ui.ensemble.window import EnsemblePage
        from ui.widgets.vocal_split_row import VocalSplitRow
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        ensemble = window._ensemble_page
        self.assertIsInstance(ensemble, EnsemblePage)
        self.assertIsInstance(ensemble.vocal_split_row, VocalSplitRow)

    def test_the_two_pages_share_one_set_of_values(self):
        """They are global keys: editing one page must be visible on the other."""
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        window.vocal_split_row.deverb_switch.set_active(True)
        window.vocal_split_row.persist_to_settings(window.settings)
        ensemble_row = window._ensemble_page.vocal_split_row
        ensemble_row.apply_from_settings(window.settings)
        self.assertTrue(ensemble_row.deverb_switch.get_active())

    def test_audio_tools_does_not_get_the_row(self):
        """Audio Tools runs no separations, so the globals do not belong there."""
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        audio_tools = window._pages["audio_tools"]
        self.assertFalse(hasattr(audio_tools, "vocal_split_row"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Confirm the page registry key for the Audio Tools assertion**

The new `test_audio_tools_does_not_get_the_row` reads `window._pages["audio_tools"]`. Confirm that registry and its key exist:

Run: `rg -n "self\._pages" ui/window.py | head -5`

`ui/window.py:404` shows a dict literal containing `"ensemble": self._ensemble_page`. Use whatever key that dict actually uses for the Audio Tools page. If there is no such registry, assert against whatever attribute holds the Audio Tools page instead — the point of the test is that the page has no `vocal_split_row`, not how you reach it.

- [ ] **Step 4: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_vocal_split_placement -v`

Expected: FAIL — `test_base_module_no_longer_builds_the_section` fails because the source still contains `voc_split_expander`, and the placement tests fail with `AttributeError: 'MainWindow' object has no attribute 'vocal_split_row'`.

- [ ] **Step 5: Delete the section from the view base**

In `ui/views/base.py`, delete the whole block from the comment `# Vocal splitter and deverb (shared global options, surfaced per method).` through `group.add(self.voc_split_expander)` (lines 717-734 at plan time).

Then remove any import that is now unused. Run:

```bash
rg -n "DEVERB_MAPPER|IS_VOC_SPLIT_MODEL_SELECT_HELP|VOC_SPLIT_MODEL_SELECT_HELP|IS_VOC_SPLIT_INST_SAVE_SELECT_HELP|IS_DEVERB_VOC_HELP|IS_DEVERB_OPT_HELP" ui/views/base.py
```

Any name that now appears **only** in the import block must be removed from that import.

- [ ] **Step 6: Add the row to the Separation Processing group**

In `ui/window.py`, add the import near the other widget imports:

```python
from .widgets.vocal_split_row import VocalSplitRow
```

In `_build_shared_group` (line 601), after `group.add(self.sample_row)` and before `return group`:

```python
        self.vocal_split_row = VocalSplitRow(
            self.context.repo, self._on_vocal_split_changed, hints=self._hint_manager
        )
        group.add(self.vocal_split_row)
```

- [ ] **Step 7: (already resolved — no action)**

`self._hint_manager` is assigned at `ui/window.py:278`, well before `_build_shared_group()` is called at `:341`, so the `hints=self._hint_manager` argument in Step 6 is safe as written. Confirm with `rg -n "_hint_manager = " ui/window.py` and move on.

- [ ] **Step 8: Wire the Separation load and flush**

In `ui/window.py`, beside the existing `self.format_row.apply_from_settings(self.settings)` (line 684), add:

```python
        self.vocal_split_row.apply_from_settings(self.settings)
```

Add the change handler next to `_on_format_changed` (line 852), mirroring its shape exactly:

```python
    def _on_vocal_split_changed(self, *_args) -> None:
        self.vocal_split_row.persist_to_settings(self.settings)
```

`MainWindow` has no `_touch_settings` method — `_on_format_changed` is just a `persist_to_settings` call, and this matches it. The write is idempotent (the row also persists into the same settings object itself), which is deliberate: the handler keeps the same contract as every other row on this page rather than being a special case that silently relies on the widget.

In the flush path beside `self.format_row.persist_to_settings(self.settings)` (line 913), add:

```python
            self.vocal_split_row.persist_to_settings(self.settings)
```

Match the surrounding indentation — that call sits inside the `content_stack.get_visible_child_name() == "separation"` guard, and the vocal-split write belongs inside the same guard for the same reason (it must not push the Separation page's state while another tab is visible).

- [ ] **Step 9: Do the same for the Ensemble page**

In `ui/ensemble/window.py` (the class is `EnsemblePage`, line 132), add the import beside the `OutputFormatRow` import (line 106):

```python
from ..widgets.vocal_split_row import VocalSplitRow
```

In the Processing group builder (line 366), after the last existing `group.add(...)` in that method:

```python
        self.vocal_split_row = VocalSplitRow(
            self.context.repo, self._on_vocal_split_changed
        )
        group.add(self.vocal_split_row)
```

`hints` is omitted: the ensemble window uses `set_tooltip` rather than a hint manager, and passing `None` simply skips registration.

Confirm the repo accessor with `rg -n "self.context.repo|self.repo" ui/ensemble/window.py | head -3` and use whichever spelling that file already uses.

Beside `self.format_row.apply_from_settings(self.settings)` (line 446):

```python
            self.vocal_split_row.apply_from_settings(self.settings)
```

Add a handler next to `_on_format_changed` (line 500), which reads:

```python
    def _on_format_changed(self, *_args) -> None:
        if not self._loading:
            self.format_row.persist_to_settings(self.settings)
```

Mirror it — do **not** delegate to it, or the ensemble page would persist the format row on a vocal-split change:

```python
    def _on_vocal_split_changed(self, *_args) -> None:
        if not self._loading:
            self.vocal_split_row.persist_to_settings(self.settings)
```

- [ ] **Step 10: Run the placement test**

Run: `.venv/bin/python -m unittest tests.test_vocal_split_placement -v`

Expected: PASS, 5 tests (2 headless + 3 GTK, the latter skipped without a display).

- [ ] **Step 11: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -20`

Expected: OK. Any test that asserted on the old per-view vocal-split rows will fail here — find them with `rg -n "vocal_split|is_set_vocal_splitter|deverb" tests/` and update them to the new location rather than deleting the assertion.

- [ ] **Step 12: Commit**

```bash
git add ui/views/base.py ui/window.py ui/ensemble/window.py tests/test_vocal_split_placement.py
git commit -m "fix(ui): move vocal splitter and deverb out of the architecture tabs

These are unprefixed global keys, but the section was built once per method
view, so three copies edited one set of values -- changing it on the VR tab
silently changed MDX-Net and Demucs.

It now sits in the Processing group on the Separation and Ensemble pages,
the two surfaces that run separations and consume those globals, matching
how OutputFormatRow already handles save_format.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Model maintenance group

**Files:**
- Modify: `ui/views/base.py` (`_build_secondary_section`, the `change_row` block)
- Test: `tests/test_model_maintenance_group.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `MethodView.maintenance_group: Adw.PreferencesGroup`, appended to `self.groups` immediately after `self.secondary_group`. `MethodView.change_row: Adw.ActionRow` becomes a public attribute (it is currently a local).

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_maintenance_group.py`:

```python
"""Change-model-defaults lives in its own group, not among the extra models."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class MaintenanceGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.maintenance-group")
        cls._app.register()

    def _views(self):
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window, window._views

    def test_every_view_has_a_maintenance_group(self):
        _window, views = self._views()
        for view in views:
            self.assertIsNotNone(view.maintenance_group, view.stack_name)

    def test_the_group_is_titled_model_maintenance(self):
        _window, views = self._views()
        for view in views:
            self.assertEqual(
                view.maintenance_group.get_title(), "Model maintenance", view.stack_name
            )

    def test_the_change_row_left_the_extra_models_group(self):
        _window, views = self._views()
        for view in views:
            self.assertIs(
                view.change_row.get_parent().get_parent(),
                view.maintenance_group,
                view.stack_name,
            )

    def test_maintenance_follows_secondary_in_the_group_order(self):
        _window, views = self._views()
        for view in views:
            groups = view.groups
            self.assertEqual(
                groups.index(view.maintenance_group),
                groups.index(view.secondary_group) + 1,
                view.stack_name,
            )


if __name__ == "__main__":
    unittest.main()
```

`test_the_change_row_left_the_extra_models_group` walks two parents because `Adw.PreferencesGroup` wraps its rows in an internal list box. If that assertion proves brittle, replace it by iterating the group's rows: `Adw.PreferencesGroup` has no public row iterator, so instead assert `view.change_row not in _rows_of(view.secondary_group)` using a helper that walks `get_first_child()` / `get_next_sibling()`. Prefer whichever the codebase already does — check with `rg -n "get_next_sibling" tests/`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_maintenance_group -v`

Expected: FAIL with `AttributeError: 'MdxView' object has no attribute 'maintenance_group'`.

- [ ] **Step 3: Move the row into its own group**

In `ui/views/base.py`, replace the change-model-defaults block at the end of `_build_secondary_section`:

```python
        # Change-model-defaults entry point.
        change_row = Adw.ActionRow(title="Change model defaults", subtitle="Edit or delete a model's stored parameters")
        change_button = Gtk.Button(label="Edit…", valign=Gtk.Align.CENTER)
        change_button.connect("clicked", self._on_change_defaults)
        change_row.add_suffix(change_button)
        change_row.set_activatable_widget(change_button)
        self.hints.register(change_row, CLEAR_CACHE_HELP)
        group.add(change_row)

        self.groups.append(self.secondary_group)
```

with:

```python
        self.groups.append(self.secondary_group)

        # Model maintenance: editing an architecture's stored model parameters
        # is not an "extra model", so it gets its own group rather than sitting
        # as a fourth sibling among the model selectors.
        self.maintenance_group = Adw.PreferencesGroup(title="Model maintenance")
        self.change_row = Adw.ActionRow(
            title="Change model defaults",
            subtitle="Edit or delete a model's stored parameters",
        )
        change_button = Gtk.Button(label="Edit…", valign=Gtk.Align.CENTER)
        change_button.connect("clicked", self._on_change_defaults)
        self.change_row.add_suffix(change_button)
        self.change_row.set_activatable_widget(change_button)
        self.hints.register(self.change_row, CLEAR_CACHE_HELP)
        self.maintenance_group.add(self.change_row)
        self.groups.append(self.maintenance_group)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_model_maintenance_group -v`

Expected: PASS, 4 tests (skipped without a display).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -20`

Expected: OK. The sheet does not yet place `maintenance_group` — that lands in Task 8. Until then the group exists in `view.groups` but is not reparented, which is harmless.

- [ ] **Step 6: Commit**

```bash
git add ui/views/base.py tests/test_model_maintenance_group.py
git commit -m "refactor(ui): give change-model-defaults its own group

Editing an architecture's stored model parameters is maintenance, not an
extra model. Splitting it out of the Extra models group stops it reading as
a fourth model selector.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Hide inapplicable secondary stem slots

**Files:**
- Modify: `ui/views/base.py` (`_build_secondary_section`, `update_stem_labels`)
- Test: `tests/test_secondary_slot_visibility.py`

**Interfaces:**
- Consumes: `ui.option_summaries.four_stem_secondaries_apply` (Task 1).
- Produces:
  - `MethodView._secondary_slot_rows: dict[str, list]` — slot name → the rows built for it (combo + scale).
  - `MethodView._sync_secondary_slot_visibility() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_secondary_slot_visibility.py`:

```python
"""Secondary stem slots that cannot affect the run are hidden, not dimmed."""

from __future__ import annotations

import os
import unittest

from bundled.constants import ALL_STEMS, ENSEMBLE_MODE, FOUR_STEM_ENSEMBLE


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SecondarySlotVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.secondary-slots")
        cls._app.register()

    def _window(self):
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window

    def _view(self, window, stack_name):
        return window._views_by_stack[stack_name]

    def test_mdx_hides_other_bass_drums_by_default(self):
        window = self._window()
        view = self._view(window, "mdx")
        view._sync_secondary_slot_visibility()
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertFalse(row.get_visible(), f"{slot} should be hidden")

    def test_the_vocals_instrumental_slot_is_always_visible(self):
        window = self._window()
        view = self._view(window, "mdx")
        view._sync_secondary_slot_visibility()
        for row in view._secondary_slot_rows["voc_inst"]:
            self.assertTrue(row.get_visible())

    def test_demucs_with_all_stems_shows_every_slot(self):
        window = self._window()
        window.settings.set("demucs_stems", ALL_STEMS)
        view = self._view(window, "demucs")
        view._sync_secondary_slot_visibility()
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertTrue(row.get_visible(), f"{slot} should be visible")

    def test_a_four_stem_ensemble_shows_every_slot_on_every_architecture(self):
        window = self._window()
        window.settings.set("chosen_process_method", ENSEMBLE_MODE)
        window.settings.set("ensemble_main_stem", FOUR_STEM_ENSEMBLE)
        for stack_name in ("vr", "mdx", "demucs"):
            view = self._view(window, stack_name)
            view._sync_secondary_slot_visibility()
            for slot in ("other", "bass", "drums"):
                for row in view._secondary_slot_rows[slot]:
                    self.assertTrue(row.get_visible(), f"{stack_name}/{slot}")

    def test_hidden_slots_keep_their_stored_values(self):
        window = self._window()
        window.settings.set("mdx_bass_secondary_model", "VR Arc: 1_HP-UVR")
        view = self._view(window, "mdx")
        view._sync_secondary_slot_visibility()
        self.assertEqual(
            window.settings.get("mdx_bass_secondary_model"), "VR Arc: 1_HP-UVR"
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_secondary_slot_visibility -v`

Expected: FAIL with `AttributeError: ... has no attribute '_sync_secondary_slot_visibility'`.

- [ ] **Step 3: Record the rows per slot while building them**

In `ui/views/base.py`, in `_build_secondary_section`, initialise the registry before the slot loop and record each slot's two rows. Replace the existing loop body:

```python
            dependents = []
            for slot, pair, primary, secondary in _SECONDARY_SLOTS:
                model_key = f"{prefix}_{slot}_secondary_model"
                scale_key = f"{prefix}_{slot}_secondary_model_scale"
                provider = (lambda p=primary, s=secondary: repo.model_list(settings, p, s))
                dependents.append(
                    self._add_model_combo(self.secondary_expander, model_key, provider, pair, hint=SECONDARY_MODEL_HELP)
                )
                dependents.append(
                    self.add_option_scale(
                        self.secondary_expander,
                        scale_key,
                        f"{pair} influence",
                        lower=0.01,
                        upper=0.99,
                        step=0.01,
                        digits=2,
                        hint=SECONDARY_MODEL_SCALE_HELP,
                        store_float=True,
                    )
                )
```

with:

```python
            dependents = []
            self._secondary_slot_rows = {}
            for slot, pair, primary, secondary in _SECONDARY_SLOTS:
                model_key = f"{prefix}_{slot}_secondary_model"
                scale_key = f"{prefix}_{slot}_secondary_model_scale"
                provider = (lambda p=primary, s=secondary: repo.model_list(settings, p, s))
                combo = self._add_model_combo(
                    self.secondary_expander, model_key, provider, pair, hint=SECONDARY_MODEL_HELP
                )
                scale = self.add_option_scale(
                    self.secondary_expander,
                    scale_key,
                    f"{pair} influence",
                    lower=0.01,
                    upper=0.99,
                    step=0.01,
                    digits=2,
                    hint=SECONDARY_MODEL_SCALE_HELP,
                    store_float=True,
                )
                dependents.extend((combo, scale))
                self._secondary_slot_rows[slot] = [combo, scale]
```

- [ ] **Step 4: Give the class a safe default for the registry**

Views without `secondary_prefix` never enter that branch. Find the other instance-attribute defaults in `MethodView.__init__` (near `self._model_combos = []`) and add:

```python
        self._secondary_slot_rows: Dict[str, list] = {}
```

Run `rg -n "self._model_combos = \[\]" ui/views/base.py` to locate the block, and match its existing typing style (if the file does not annotate those attributes, do not annotate this one either). Confirm `Dict` is imported with `rg -n "^from typing import" ui/views/base.py`; if not, use a bare assignment.

- [ ] **Step 5: Add the visibility sync**

Add the import at the top of `ui/views/base.py`:

```python
from ..option_summaries import four_stem_secondaries_apply
```

Verify the relative depth first: `ui/views/base.py` is two levels down, so `..option_summaries` is correct for a module at `ui/option_summaries.py`. Confirm with `rg -n "^from \.\." ui/views/base.py | head -3`.

Add the method next to `_sync_switch_dependents` (line 649):

```python
    def _sync_secondary_slot_visibility(self) -> None:
        """Hide the secondary slots that cannot affect this run.

        ``other`` / ``bass`` / ``drums`` only ever feed the engine's four-source
        branch. Hiding rather than dimming is deliberate: the height is the
        point, and stem count is a structural fact about the run rather than a
        toggle the user is expected to flip. Stored values are untouched, so the
        slots come back populated when a four-source run is selected again.
        """
        rows_by_slot = getattr(self, "_secondary_slot_rows", None)
        if not rows_by_slot:
            return
        four_stem = four_stem_secondaries_apply(self.settings, self.method_key)
        for slot, rows in rows_by_slot.items():
            visible = True if slot == "voc_inst" else four_stem
            for row in rows:
                row.set_visible(visible)
```

Confirm the attribute holding the architecture key: run `rg -n "method_key|method_key_for_resolution" ui/views/base.py | head -5`. Use `self.method_key` if it holds the raw architecture type; if the raw type lives on `method_key_for_resolution`, use that instead — `four_stem_secondaries_apply` compares against `DEMUCS_ARCH_TYPE`.

- [ ] **Step 6: Call it from the existing refresh point**

In `update_stem_labels` (line 267), add the call as the last line of the method, after `self._update_stem_group_metadata()`:

```python
        self._sync_secondary_slot_visibility()
```

`update_stem_labels` is the documented refresh point: it already runs on load (line 377), on model change, and after stem-group changes.

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_secondary_slot_visibility -v`

Expected: PASS, 5 tests (skipped without a display).

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -20`

Expected: OK.

- [ ] **Step 9: Commit**

```bash
git add ui/views/base.py tests/test_secondary_slot_visibility.py
git commit -m "feat(ui): hide secondary stem slots that cannot affect the run

The other/bass/drums secondary slots only feed the engine's four-source
branch (Demucs with all stems, any 4-stem ensemble member, or a Demucs
member of a multi-stem ensemble). Everywhere else they were three dead
model pickers and three dead scales.

Hidden slots keep their stored values and return when a four-source run
is selected.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Expander subtitles and auto-expand in the views

**Files:**
- Modify: `ui/views/base.py` (`_build_secondary_section`, `load`, `update_stem_labels`)
- Test: `tests/test_expander_summaries.py`

**Interfaces:**
- Consumes: `ui.option_summaries.secondary_models_summary`, `preproc_summary`, `four_stem_secondaries_apply` (Task 1); `MethodView._sync_secondary_slot_visibility` (Task 5).
- Produces: `MethodView._sync_expander_summaries() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_expander_summaries.py`:

```python
"""Collapsed option expanders show their live state."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ExpanderSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.expander-summaries")
        cls._app.register()

    def _window(self):
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window

    def test_secondary_expander_reports_off_when_disabled(self):
        from ui.option_summaries import OFF

        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", False)
        view = window._views_by_stack["mdx"]
        view._sync_expander_summaries()
        self.assertEqual(view.secondary_expander.get_subtitle(), OFF)

    def test_secondary_expander_auto_expands_when_enabled(self):
        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", True)
        view = window._views_by_stack["mdx"]
        view._sync_expander_summaries()
        self.assertTrue(view.secondary_expander.get_expanded())

    def test_secondary_expander_stays_collapsed_when_disabled(self):
        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", False)
        view = window._views_by_stack["mdx"]
        view.secondary_expander.set_expanded(False)
        view._sync_expander_summaries()
        self.assertFalse(view.secondary_expander.get_expanded())

    def test_a_manually_opened_expander_is_never_auto_collapsed(self):
        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", False)
        view = window._views_by_stack["mdx"]
        view.secondary_expander.set_expanded(True)
        view._sync_expander_summaries()
        self.assertTrue(view.secondary_expander.get_expanded())

    def test_preproc_expander_reports_off_when_disabled(self):
        from ui.option_summaries import OFF

        window = self._window()
        window.settings.set("is_demucs_pre_proc_model_activate", False)
        view = window._views_by_stack["demucs"]
        view._sync_expander_summaries()
        self.assertEqual(view.preproc_expander.get_subtitle(), OFF)

    def test_views_without_a_preproc_section_are_skipped(self):
        window = self._window()
        view = window._views_by_stack["mdx"]
        self.assertFalse(hasattr(view, "preproc_expander"))
        view._sync_expander_summaries()  # must not raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_expander_summaries -v`

Expected: FAIL with `AttributeError: ... has no attribute '_sync_expander_summaries'`.

- [ ] **Step 3: Extend the import**

In `ui/views/base.py`, extend the Task 5 import:

```python
from ..option_summaries import (
    four_stem_secondaries_apply,
    preproc_summary,
    secondary_models_summary,
)
```

- [ ] **Step 4: Add the sync method**

Add next to `_sync_secondary_slot_visibility`:

```python
    def _sync_expander_summaries(self) -> None:
        """Refresh each option expander's subtitle, and open what is switched on.

        Expand only -- never auto-collapse. A section the user opened by hand
        must not be shut on them by an unrelated settings reload.
        """
        secondary = getattr(self, "secondary_expander", None)
        if secondary is not None and self.secondary_prefix:
            four_stem = four_stem_secondaries_apply(self.settings, self.method_key)
            secondary.set_subtitle(
                secondary_models_summary(
                    self.settings, self.secondary_prefix, four_stem=four_stem
                )
            )
            if self.settings.get(
                f"{self.secondary_prefix}_is_secondary_model_activate"
            ):
                secondary.set_expanded(True)

        preproc = getattr(self, "preproc_expander", None)
        if preproc is not None:
            preproc.set_subtitle(preproc_summary(self.settings))
            if self.settings.get("is_demucs_pre_proc_model_activate"):
                preproc.set_expanded(True)
```

Use the same `self.method_key` / `self.method_key_for_resolution` choice settled in Task 5 Step 5.

- [ ] **Step 5: Keep the subtitles live**

The activate switches already have handlers via `_bind_switch_dependents`. Extend that method so every applier also refreshes the subtitles. In `_bind_switch_dependents` (line 628), change the inner `apply`:

```python
        def apply(*_args) -> None:
            active = switch_row.get_active()
            for row in rows:
                row.set_sensitive(active)
```

to:

```python
        def apply(*_args) -> None:
            active = switch_row.get_active()
            for row in rows:
                row.set_sensitive(active)
            # Guarded: tests exercise this on a bare ``__new__`` instance, which
            # has no settings to summarise.
            if getattr(self, "settings", None) is not None:
                self._refresh_expander_subtitles()
```

Then split the subtitle half out of `_sync_expander_summaries` so the switch handler never force-expands (that would fight a user collapsing a section that is switched on):

```python
    def _refresh_expander_subtitles(self) -> None:
        """Subtitle-only half of :meth:`_sync_expander_summaries` (no expanding)."""
        secondary = getattr(self, "secondary_expander", None)
        if secondary is not None and self.secondary_prefix:
            four_stem = four_stem_secondaries_apply(self.settings, self.method_key)
            secondary.set_subtitle(
                secondary_models_summary(
                    self.settings, self.secondary_prefix, four_stem=four_stem
                )
            )
        preproc = getattr(self, "preproc_expander", None)
        if preproc is not None:
            preproc.set_subtitle(preproc_summary(self.settings))
```

and rewrite `_sync_expander_summaries` to reuse it:

```python
    def _sync_expander_summaries(self) -> None:
        """Refresh subtitles, then open whatever is switched on.

        Expand only -- never auto-collapse. A section the user opened by hand
        must not be shut on them by an unrelated settings reload.
        """
        self._refresh_expander_subtitles()
        if (
            getattr(self, "secondary_expander", None) is not None
            and self.secondary_prefix
            and self.settings.get(
                f"{self.secondary_prefix}_is_secondary_model_activate"
            )
        ):
            self.secondary_expander.set_expanded(True)
        if (
            getattr(self, "preproc_expander", None) is not None
            and self.settings.get("is_demucs_pre_proc_model_activate")
        ):
            self.preproc_expander.set_expanded(True)
```

- [ ] **Step 6: Call the full sync on load**

In `load` (line 364), after the existing `self._sync_switch_dependents()` at line 376 and after `self.update_stem_labels()` at line 377 (the summary depends on slot visibility, which `update_stem_labels` sets), add:

```python
        self._sync_expander_summaries()
```

Place it immediately before `self.hints.refresh()`.

- [ ] **Step 7: Keep the secondary subtitle in step with slot visibility**

`secondary_models_summary` takes `four_stem`, so its subtitle must never describe a slot the section is hiding. Task 5 put `_sync_secondary_slot_visibility()` at the end of `update_stem_labels`; add the subtitle refresh directly after it, so both halves move together:

```python
        self._sync_secondary_slot_visibility()
        if getattr(self, "settings", None) is not None:
            self._refresh_expander_subtitles()
```

Subtitles only — not the full `_sync_expander_summaries`. `update_stem_labels` runs on every model change, and force-expanding a section on each one would fight a user who just collapsed it.

- [ ] **Step 8: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_expander_summaries -v`

Expected: PASS, 6 tests (skipped without a display).

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -20`

Expected: OK. `tests/test_switch_dependents.py` exercises `_bind_switch_dependents` on a bare `__new__` instance — the `getattr(self, "settings", None)` guard added in Step 5 is what keeps it green. If it fails, the guard is wrong, not the test.

- [ ] **Step 10: Commit**

```bash
git add ui/views/base.py tests/test_expander_summaries.py
git commit -m "feat(ui): show live state on collapsed option expanders

Each option expander now carries a one-line summary of what it is set to,
and any section that is switched on opens automatically. Expanding only --
a section the user collapsed by hand is never reopened against them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: `applicability_banner`

**Files:**
- Modify: `ui/model_options/applicability.py:102-134`
- Modify: `ui/model_options/__init__.py:8,20`
- Modify: `tests/test_model_options_applicability.py:12,82`
- Test: `tests/test_model_options_applicability.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `applicability_banner(context: str, stack_name: str, *, active_method_key: str, selected_models) -> Optional[Tuple[str, Optional[str]]]` — `(banner_text, button_label)`, or `None` when the tab is applicable and needs no banner. `button_label` is `None` when the banner offers no action.
  - `applicability_subtitle` is **removed**.

- [ ] **Step 1: Read the current function and its test**

Read [ui/model_options/applicability.py:102-134](../../../ui/model_options/applicability.py#L102-L134) and [tests/test_model_options_applicability.py](../../../tests/test_model_options_applicability.py) in full. The new function keeps the same context/stack logic; only the return shape and the "applicable" case change.

- [ ] **Step 2: Write the failing test**

Replace the `applicability_subtitle` import at `tests/test_model_options_applicability.py:12` with `applicability_banner`, delete the old subtitle test at line 82, and append:

```python
class ApplicabilityBannerTests(unittest.TestCase):
    def test_applicable_separation_tab_gets_no_banner(self):
        self.assertIsNone(
            applicability_banner(
                OPEN_CONTEXT_SEPARATION,
                "mdx",
                active_method_key=MDX_ARCH_TYPE,
                selected_models=[],
            )
        )

    def test_inactive_separation_tab_names_the_active_method(self):
        result = applicability_banner(
            OPEN_CONTEXT_SEPARATION,
            "vr",
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertIsNotNone(result)
        text, button = result
        self.assertIn("MDX-Net", text)
        self.assertIn("VR Architecture", button)

    def test_unused_ensemble_tab_says_no_member_uses_it(self):
        result = applicability_banner(
            OPEN_CONTEXT_ENSEMBLE,
            "demucs",
            active_method_key="",
            selected_models=[f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Some Model"],
        )
        self.assertIsNotNone(result)
        text, button = result
        self.assertIn("no ensemble members", text.lower())
        self.assertIsNone(button)

    def test_used_ensemble_tab_gets_no_banner(self):
        self.assertIsNone(
            applicability_banner(
                OPEN_CONTEXT_ENSEMBLE,
                "mdx",
                active_method_key="",
                selected_models=[f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Some Model"],
            )
        )

    def test_empty_ensemble_prompts_for_members_on_every_tab(self):
        for stack_name in ("vr", "mdx", "demucs"):
            result = applicability_banner(
                OPEN_CONTEXT_ENSEMBLE,
                stack_name,
                active_method_key="",
                selected_models=[],
            )
            self.assertIsNotNone(result, stack_name)
            text, button = result
            self.assertIn("Select ensemble member models", text)
            self.assertIsNone(button)

    def test_audio_tools_context_is_never_applicable(self):
        result = applicability_banner(
            OPEN_CONTEXT_AUDIO_TOOLS,
            "mdx",
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertIsNotNone(result)
```

Add whatever imports these need (`ENSEMBLE_PARTITION`, `OPEN_CONTEXT_SEPARATION`, `OPEN_CONTEXT_AUDIO_TOOLS`, `MDX_ARCH_TYPE`) to the file's existing import block — check what is already imported before adding.

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_options_applicability -v`

Expected: FAIL with `ImportError: cannot import name 'applicability_banner'`.

- [ ] **Step 4: Replace the function**

In `ui/model_options/applicability.py`, replace `applicability_subtitle` (lines 102-134) with:

```python
def applicability_banner(
    context: str,
    stack_name: str,
    *,
    active_method_key: str,
    selected_models: Sequence[str],
) -> Optional[tuple[str, Optional[str]]]:
    """The banner for one architecture tab, or ``None`` when it needs none.

    Returns ``(text, button_label)``. ``button_label`` is ``None`` for a banner
    with no action. An applicable tab returns ``None`` outright -- absence of a
    banner is what "this tab applies" looks like, so the common case is silent.
    """
    applicable = applicable_stack_names(
        context,
        active_method_key=active_method_key,
        selected_models=selected_models,
    )
    title = _STACK_TITLES.get(stack_name, stack_name)

    if context == OPEN_CONTEXT_AUDIO_TOOLS:
        return ("These options only apply to Separation and Ensemble runs.", None)

    if context == OPEN_CONTEXT_SEPARATION:
        if stack_name in applicable:
            return None
        active_title = _STACK_TITLES.get(
            stack_name_for_method_key(active_method_key) or "", "another architecture"
        )
        return (
            f"Not used by this run — the active method is {active_title}.",
            f"Switch to {title}",
        )

    if context == OPEN_CONTEXT_ENSEMBLE:
        if not applicable:
            return (
                "Select ensemble member models before editing "
                "architecture-specific options.",
                None,
            )
        if stack_name in applicable:
            return None
        return ("Not used — no ensemble members use this architecture.", None)

    return None
```

- [ ] **Step 5: Update the package export**

In `ui/model_options/__init__.py`, change `applicability_subtitle` to `applicability_banner` in both the import (line 8) and `__all__` (line 20).

- [ ] **Step 6: Confirm the sheet no longer references the old name**

Run: `rg -n "applicability_subtitle" ui/ tests/`

Expected: **no matches.** Task 8 runs before this task (see "Execution order" at the top of this plan) and already deleted the sheet's subtitle rendering along with its import, so removing the function here breaks nothing.

If there are matches, Task 8 was skipped or left work behind — stop and report rather than adding a shim.

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_model_options_applicability -v`

Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -20`

Expected: OK.

- [ ] **Step 9: Commit**

```bash
git add ui/model_options/applicability.py ui/model_options/__init__.py ui/model_options/sheet.py tests/test_model_options_applicability.py
git commit -m "refactor(ui): return banner content instead of a subtitle string

applicability_banner returns (text, button_label) or None, so an applicable
tab is silent rather than carrying a dim label saying it applies. The sheet
keeps a temporary shim until the next commit rewires it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Sheet shell — width cap, content height, two non-homogeneous columns

**Files:**
- Modify: `ui/model_options/sheet.py:1-148`, `:216-289`
- Test: `tests/test_model_options_sheet_layout.py`

**Interfaces:**
- Consumes: `MethodView.maintenance_group` (Task 4).
- Produces:
  - Module constants `_SHEET_WIDTH = 760`, `_SHEET_FALLBACK_HEIGHT = 560`, `_SHEET_MAX_HEIGHT_FRACTION = 0.9`, `_STACK_BREAKPOINT = 700`
  - `ModelOptionsSheet._sheet_height() -> int`
  - `ModelOptionsSheet._tab_columns: Dict[str, Gtk.Box]` retained (drives the stacking flip)
  - Removed: `_sync_from_parent_width`, `_start_width_tracking`, `_stop_width_tracking`, `_last_parent_width`, `_surface_handler`, `_parent_map_handler`, `_on_closed`, `_SHEET_WIDE_WIDTH`, `_SHEET_WIDE_HEIGHT`, `_NARROW_BREAKPOINT`

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_options_sheet_layout.py`:

```python
"""Sheet shell: capped width, content-driven height, balanced columns."""

from __future__ import annotations

import os
import unittest


class SheetConstantsTests(unittest.TestCase):
    """Headless: the sizing policy is expressed as module constants."""

    def test_width_is_capped_not_parent_tracked(self):
        from ui.model_options import sheet

        self.assertEqual(sheet._SHEET_WIDTH, 760)

    def test_height_fraction_leaves_room_for_the_parent_window(self):
        from ui.model_options import sheet

        self.assertEqual(sheet._SHEET_MAX_HEIGHT_FRACTION, 0.9)

    def test_parent_width_tracking_is_gone(self):
        from ui.model_options import sheet

        for name in (
            "_sync_from_parent_width",
            "_start_width_tracking",
            "_stop_width_tracking",
        ):
            self.assertFalse(
                hasattr(sheet.ModelOptionsSheet, name), f"{name} should be removed"
            )

    def test_the_sheet_no_longer_reaches_parent_window_width(self):
        import inspect

        from ui.model_options import sheet

        source = inspect.getsource(sheet)
        self.assertNotIn("parent_window_width", source)
        self.assertNotIn("configure_dialog_width", source)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SheetLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.sheet-layout")
        cls._app.register()

    def _sheet(self):
        from ui.model_options.sheet import ModelOptionsSheet
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return ModelOptionsSheet(
            window,
            views=window._views,
            views_by_stack=window._views_by_stack,
            settings=window.settings,
        ), window

    def test_content_width_is_the_cap(self):
        from ui.model_options import sheet as sheet_module

        sheet, _window = self._sheet()
        self.assertEqual(sheet.dialog.get_content_width(), sheet_module._SHEET_WIDTH)

    def test_columns_are_not_homogeneous(self):
        sheet, _window = self._sheet()
        for columns_box in sheet._tab_columns.values():
            self.assertFalse(columns_box.get_homogeneous())

    def test_every_tab_carries_all_three_groups(self):
        sheet, window = self._sheet()
        for stack_name, view in window._views_by_stack.items():
            for group in (
                view.advanced_group,
                view.secondary_group,
                view.maintenance_group,
            ):
                self.assertIsNotNone(
                    group.get_parent(), f"{stack_name}: group not placed"
                )

    def test_maintenance_sits_below_secondary_in_the_end_column(self):
        sheet, window = self._sheet()
        for stack_name, view in window._views_by_stack.items():
            self.assertIs(
                view.maintenance_group.get_parent(),
                view.secondary_group.get_parent(),
                stack_name,
            )

    def test_inference_is_alone_in_the_start_column(self):
        sheet, window = self._sheet()
        for stack_name, view in window._views_by_stack.items():
            self.assertIsNot(
                view.advanced_group.get_parent(),
                view.secondary_group.get_parent(),
                stack_name,
            )

    def test_height_falls_back_when_the_parent_is_unrealized(self):
        from ui.model_options import sheet as sheet_module

        sheet, _window = self._sheet()
        self.assertEqual(sheet._sheet_height(), sheet_module._SHEET_FALLBACK_HEIGHT)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_options_sheet_layout -v`

Expected: FAIL with `AttributeError: module 'ui.model_options.sheet' has no attribute '_SHEET_WIDTH'`.

- [ ] **Step 3: Replace the constants and the import block**

In `ui/model_options/sheet.py`, replace lines 9-26:

```python
from ..dialogs.utils import configure_dialog_width, parent_window_width, present_modal_dialog
from ..spacing import inset_md
from ..widgets.columns import build_columns_box, set_columns_narrow
from .applicability import (
    OPEN_CONTEXT_AUDIO_TOOLS,
    OPEN_CONTEXT_ENSEMBLE,
    applicable_stack_names,
    applicability_banner,
    default_stack_name,
    ensemble_context_banner,
    should_hide_unused_stacks,
)

_SHEET_WIDE_WIDTH = 900
_SHEET_WIDE_HEIGHT = 560
# Match the main window’s wide/narrow breakpoint (880sp) closely in pixels.
# This keeps the sheet’s column flip aligned with the rest of the UI.
_NARROW_BREAKPOINT = 880
```

with:

```python
from ..dialogs.utils import present_modal_dialog
from ..spacing import inset_md
from .applicability import (
    OPEN_CONTEXT_AUDIO_TOOLS,
    OPEN_CONTEXT_ENSEMBLE,
    applicable_stack_names,
    default_stack_name,
    ensemble_context_banner,
    should_hide_unused_stacks,
)

#: The sheet is a modal options surface, not a second window: it is capped
#: rather than sized to the parent. Dropping parent-width tracking also drops
#: the sheet's two call sites into ``parent_window_width``.
_SHEET_WIDTH = 760
#: Used when the parent's allocated height is not yet known (unrealized window).
_SHEET_FALLBACK_HEIGHT = 560
#: Never take more than this share of the parent's height.
_SHEET_MAX_HEIGHT_FRACTION = 0.9
#: Below this content width the two columns stack into one.
_STACK_BREAKPOINT = 700
```

- [ ] **Step 4: Add a local non-homogeneous columns builder**

`ui/widgets/columns.py` builds *homogeneous* columns for the main pages and is used by several other callers — do not change it. Add a private builder to `ui/model_options/sheet.py`, after the constants:

```python
def _build_sheet_columns():
    """Two content-sized columns for one tab page.

    Unlike ``ui.widgets.columns.build_columns_box`` these are **not**
    homogeneous: the Inference group and the Extra models + Model maintenance
    stack have genuinely different natural widths, and forcing them equal is
    what left the MDX-Net tab showing two rows beside a column of expanders.
    """
    col_start = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=18,
        hexpand=True,
        valign=Gtk.Align.START,
    )
    col_end = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=18,
        hexpand=True,
        valign=Gtk.Align.START,
    )
    columns_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
    columns_box.set_homogeneous(False)
    columns_box.set_hexpand(True)
    columns_box.append(col_start)
    columns_box.append(col_end)
    return columns_box, col_start, col_end


def _set_sheet_columns_stacked(columns_box, stacked: bool) -> None:
    """Flip a sheet columns box between stacked (narrow) and side-by-side."""
    columns_box.set_orientation(
        Gtk.Orientation.VERTICAL if stacked else Gtk.Orientation.HORIZONTAL
    )
```

- [ ] **Step 5: Update the constructor**

In `__init__`, replace the sizing block (lines 55-62):

```python
        self.dialog = Adw.Dialog()
        self.dialog.set_title("Model options")
        # Initial desktop size (will be re-synced to parent on present()).
        self.dialog.set_content_width(_SHEET_WIDE_WIDTH)
        self.dialog.set_content_height(_SHEET_WIDE_HEIGHT)
        self.dialog.set_follows_content_size(False)
        self.dialog.connect("closed", self._on_closed)
        self.dialog.connect("notify::content-width", self._sync_narrow_layout)
```

with:

```python
        self.dialog = Adw.Dialog()
        self.dialog.set_title("Model options")
        self.dialog.set_content_width(_SHEET_WIDTH)
        self.dialog.set_content_height(self._sheet_height())
        self.dialog.set_follows_content_size(False)
        self.dialog.connect("notify::content-width", self._sync_narrow_layout)
```

and delete these three instance attributes from `__init__` (lines 51-53):

```python
        self._last_parent_width: int = 0
        self._surface_handler: int = 0
        self._parent_map_handler: int = 0
```

- [ ] **Step 6: Add the height helper**

Add next to `_sync_narrow_layout`:

```python
    def _sheet_height(self) -> int:
        """Content height: follow the content, bounded by the parent's height.

        An ``Adw.Dialog`` cannot exceed its parent window, so the parent's
        allocated height is the real ceiling. Before the parent is realized
        ``get_height()`` returns 0 and the fallback applies.
        """
        parent_height = self._parent.get_height() if self._parent is not None else 0
        if parent_height <= 1:
            return _SHEET_FALLBACK_HEIGHT
        return int(parent_height * _SHEET_MAX_HEIGHT_FRACTION)
```

- [ ] **Step 7: Rewrite `_build_tab_page`**

Replace the whole method (lines 98-129) with:

```python
    def _build_tab_page(self, view) -> Gtk.Widget:
        columns_box, col_start, col_end = _build_sheet_columns()
        self._tab_columns[view.stack_name] = columns_box

        if view.advanced_group.get_parent() is not None:
            view.advanced_group.get_parent().remove(view.advanced_group)
        view.advanced_group.set_title("Inference")
        view.advanced_group.set_description(
            "Advanced processing options for this architecture"
        )
        col_start.append(view.advanced_group)

        for group in (view.secondary_group, view.maintenance_group):
            if group.get_parent() is not None:
                group.get_parent().remove(group)
            col_end.append(group)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.set_child(columns_box)

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page_box.set_vexpand(True)
        page_box.append(scroller)
        self._tab_pages[view.stack_name] = page_box
        return page_box
```

Also delete `self._tab_subtitles: Dict[str, Gtk.Label] = {}` from `__init__` (line 50) — the per-page label is gone.

- [ ] **Step 8: Rewrite `_sync_narrow_layout`**

Replace lines 131-139 with:

```python
    def _sync_narrow_layout(self, *_args) -> None:
        # Drive stacking off actual allocated content width, so the sheet adapts
        # when the parent window is narrower than the sheet's own cap.
        width = self.dialog.get_content_width()
        if width <= 0:
            width = self._parent.get_width() if self._parent is not None else 0
        stacked = 0 < width < _STACK_BREAKPOINT
        for columns_box in self._tab_columns.values():
            _set_sheet_columns_stacked(columns_box, stacked)
```

- [ ] **Step 9: Delete the width-tracking machinery**

Delete `_sync_from_parent_width` (lines 141-148), `_start_width_tracking` (150-168), `_stop_width_tracking` (170-184), and `_on_closed` (270-271).

- [ ] **Step 10: Update `present`**

Replace lines 281-282:

```python
        configure_dialog_width(self.dialog, self._parent, fallback=_SHEET_WIDE_WIDTH)
        self._start_width_tracking()
```

with:

```python
        self.dialog.set_content_width(_SHEET_WIDTH)
        self.dialog.set_content_height(self._sheet_height())
```

- [ ] **Step 11: Delete the per-page subtitle rendering**

In `_refresh_applicability`, delete the `subtitle = applicability_subtitle(...)` call and the `self._tab_subtitles[stack_name].set_label(subtitle)` line entirely (lines 249-255). Task 7 then removes the now-unreferenced `applicability_subtitle` function itself, and Task 9 adds the real banner rendering. For this commit the applicability pass just sets visibility and sensitivity.

Confirm the module no longer names it: `rg -n "applicability_subtitle" ui/model_options/sheet.py` must return nothing.

- [ ] **Step 12: Run the layout test**

Run: `.venv/bin/python -m unittest tests.test_model_options_sheet_layout -v`

Expected: PASS, 10 tests (4 headless + 6 GTK).

- [ ] **Step 13: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -20`

Expected: OK. Any existing sheet test asserting on `_SHEET_WIDE_WIDTH`, `_NARROW_BREAKPOINT` or `_tab_subtitles` fails here — find them with `rg -n "_SHEET_WIDE|_NARROW_BREAKPOINT|_tab_subtitles" tests/` and update them to the new constants.

- [ ] **Step 14: Commit**

```bash
git add ui/model_options/sheet.py tests/test_model_options_sheet_layout.py
git commit -m "refactor(ui): cap the model-options sheet and balance its columns

The sheet tracked the parent window's width through a surface notify handler
and resized to match. A modal options surface has no reason to be as wide as
the main window, so it is now capped at 760 with a content-driven height
bounded by the parent.

Columns become non-homogeneous, which is what the MDX-Net tab needed: its
two inference rows no longer sit in a column forced as wide as the expander
stack beside it. Model maintenance joins the end column.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Sheet applicability — banners, badges, method switching

**Files:**
- Modify: `ui/model_options/sheet.py` (`__init__`, `_build_tab_page`, `update_context`, `_refresh_applicability`, `present`, `open_model_options_sheet`)
- Modify: `ui/window.py` (the `open_model_options_sheet` call at line 1129, plus a new handler)
- Test: `tests/test_model_options_sheet_applicability.py`

**Interfaces:**
- Consumes: `applicability_banner` (Task 7); the sheet shell (Task 8).
- Produces:
  - `ModelOptionsSheet(parent, *, views, views_by_stack, settings, on_switch_method=None)`
  - `open_model_options_sheet(..., on_switch_method=None)`
  - `ModelOptionsSheet._tab_banners: Dict[str, Adw.Banner]`
  - `MainWindow._on_sheet_switch_method(stack_name: str) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_options_sheet_applicability.py`:

```python
"""Sheet applicability: banners on inactive tabs, badges on ensemble tabs."""

from __future__ import annotations

import os
import unittest

from bundled.constants import ENSEMBLE_PARTITION, MDX_ARCH_TYPE, VR_ARCH_TYPE
from ui.model_options.applicability import (
    OPEN_CONTEXT_ENSEMBLE,
    OPEN_CONTEXT_SEPARATION,
)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SheetApplicabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.sheet-applicability")
        cls._app.register()

    def _sheet(self, on_switch_method=None):
        from ui.model_options.sheet import ModelOptionsSheet
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        sheet = ModelOptionsSheet(
            window,
            views=window._views,
            views_by_stack=window._views_by_stack,
            settings=window.settings,
            on_switch_method=on_switch_method,
        )
        return sheet, window

    def test_active_separation_tab_has_no_visible_banner(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertFalse(sheet._tab_banners["mdx"].get_revealed())

    def test_inactive_separation_tab_reveals_a_banner(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        banner = sheet._tab_banners["vr"]
        self.assertTrue(banner.get_revealed())
        self.assertIn("MDX-Net", banner.get_title())

    def test_the_banner_offers_to_switch(self):
        sheet, _window = self._sheet(on_switch_method=lambda _name: None)
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertIn("VR Architecture", sheet._tab_banners["vr"].get_button_label())

    def test_no_button_without_a_switch_callback(self):
        sheet, _window = self._sheet(on_switch_method=None)
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertFalse(sheet._tab_banners["vr"].get_button_label())

    def test_ensemble_tabs_are_badged_with_member_counts(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_ENSEMBLE,
            active_method_key="",
            selected_models=[
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Model A",
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Model B",
                f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}Model C",
            ],
        )
        self.assertEqual(sheet._tab_stack_pages["mdx"].get_badge_number(), 2)
        self.assertEqual(sheet._tab_stack_pages["vr"].get_badge_number(), 1)

    def test_separation_context_carries_no_badges(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        for stack_name in ("vr", "mdx", "demucs"):
            self.assertEqual(
                sheet._tab_stack_pages[stack_name].get_badge_number(), 0, stack_name
            )

    def test_activating_the_banner_calls_back_with_the_stack_name(self):
        switched = []
        sheet, _window = self._sheet(on_switch_method=switched.append)
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        sheet._tab_banners["vr"].emit("button-clicked")
        self.assertEqual(switched, ["vr"])

    def test_empty_ensemble_prompts_on_every_tab(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_ENSEMBLE,
            active_method_key="",
            selected_models=[],
        )
        for stack_name in ("vr", "mdx", "demucs"):
            banner = sheet._tab_banners[stack_name]
            self.assertTrue(banner.get_revealed(), stack_name)
            self.assertIn("Select ensemble member models", banner.get_title())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_options_sheet_applicability -v`

Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'on_switch_method'`.

- [ ] **Step 3: Accept the callback**

In `ui/model_options/sheet.py`, change the constructor signature:

```python
    def __init__(
        self,
        parent: Gtk.Window,
        *,
        views: Sequence,
        views_by_stack: Dict[str, object],
        settings,
        on_switch_method: Optional[Callable[[str], None]] = None,
    ):
```

Add `Callable` to the `typing` import on line 5. Store it and add the banner registry beside the other `__init__` dicts:

```python
        self._on_switch_method = on_switch_method
        self._tab_banners: Dict[str, Adw.Banner] = {}
```

- [ ] **Step 4: Put a banner on every page**

In `_build_tab_page`, before building the scroller:

```python
        banner = Adw.Banner()
        banner.set_revealed(False)
        banner.connect(
            "button-clicked",
            lambda _banner, name=view.stack_name: self._on_banner_switch(name),
        )
        self._tab_banners[view.stack_name] = banner
```

and prepend it to the page box, above the scroller:

```python
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page_box.set_vexpand(True)
        page_box.append(banner)
        page_box.append(scroller)
```

Add the handler next to `_on_tab_changed`:

```python
    def _on_banner_switch(self, stack_name: str) -> None:
        """Hand the architecture switch back to the window, then re-read state.

        The sheet cannot switch methods itself: a correct switch also updates
        the main page's method combo and rebuilds its columns. The window owns
        both, so it does the work and the sheet just refreshes in place -- it
        deliberately does not close, so the user can keep editing.
        """
        if self._on_switch_method is None:
            return
        self._on_switch_method(stack_name)
        view = self._views_by_stack.get(stack_name)
        self.update_context(
            context=self._context,
            active_method_key=getattr(view, "method_key", self._active_method_key),
            selected_models=self._selected_models,
            initial_stack=stack_name,
        )
```

- [ ] **Step 5: Render banners and badges in `_refresh_applicability`**

Replace the body of `_refresh_applicability` (lines 223-268) with:

```python
    def _refresh_applicability(self) -> None:
        applicable = applicable_stack_names(
            self._context,
            active_method_key=self._active_method_key,
            selected_models=self._selected_models,
        )
        empty_ensemble = self._context == OPEN_CONTEXT_ENSEMBLE and not applicable
        counts = (
            member_arch_counts(self._selected_models)
            if self._context == OPEN_CONTEXT_ENSEMBLE
            else {}
        )
        # Separation: keep every architecture tab visible so options are never
        # wiped by hiding the active ViewStack child. Ensemble: hide arches
        # that no selected member uses (still show all when the list is empty).
        hide_unused = should_hide_unused_stacks(self._context, applicable)

        for stack_name, page in self._tab_pages.items():
            is_applicable = stack_name in applicable
            self._apply_banner(stack_name)

            stack_page = self._tab_stack_pages.get(stack_name)
            if stack_page is not None:
                stack_page.set_visible(is_applicable if hide_unused else True)
                if hasattr(stack_page, "set_badge_number"):
                    stack_page.set_badge_number(counts.get(stack_name, 0))

            # Separation keeps non-active arches editable for pre-config; the
            # page banner communicates that those values are unused.
            # Empty ensemble dims everything until members are chosen.
            if empty_ensemble:
                page.set_sensitive(False)
            elif hide_unused:
                page.set_sensitive(is_applicable)
            else:
                page.set_sensitive(True)
            page.set_opacity(1.0)

    def _apply_banner(self, stack_name: str) -> None:
        """Reveal, hide or relabel one page's banner from the applicability rule."""
        banner = self._tab_banners.get(stack_name)
        if banner is None:
            return
        result = applicability_banner(
            self._context,
            stack_name,
            active_method_key=self._active_method_key,
            selected_models=self._selected_models,
        )
        if result is None:
            banner.set_revealed(False)
            return
        text, button_label = result
        banner.set_title(text)
        # Offering a switch we cannot perform would be a dead button.
        banner.set_button_label(
            button_label if button_label and self._on_switch_method else ""
        )
        banner.set_revealed(True)
```

Add `member_arch_counts` to the `.applicability` import block.

- [ ] **Step 6: Move the ensemble explanation onto the group description**

In `update_context`, replace the `_ensemble_banner` block (lines 201-206):

```python
        banner_text = ensemble_context_banner(context)
        if banner_text:
            self._ensemble_banner.set_label(banner_text)
            self._ensemble_banner.set_visible(True)
        else:
            self._ensemble_banner.set_visible(False)
```

with:

```python
        # The standing ensemble explanation is context, not an alert, so it
        # rides on the Inference group's description rather than a banner.
        description = ensemble_context_banner(context) or (
            "Advanced processing options for this architecture"
        )
        for view in self._views:
            view.advanced_group.set_description(description)
```

Then delete the `_ensemble_banner` construction from `__init__` (lines 64-66) and its `body.append(self._ensemble_banner)` (line 93).

- [ ] **Step 7: Thread the callback through the module function**

In `open_model_options_sheet`, add `on_switch_method: Optional[Callable[[str], None]] = None` to the signature (before `existing`), and pass it to the `ModelOptionsSheet(...)` construction.

Note it is only used when the sheet is **constructed**. The sheet is cached on the window, so a later call with a different callback is ignored — that is fine, `MainWindow` always passes the same bound method.

- [ ] **Step 8: Implement the window side**

In `ui/window.py`, add the handler next to `_on_method_selected` (line 822):

```python
    def _on_sheet_switch_method(self, stack_name: str) -> None:
        """Switch the active architecture from the model-options sheet.

        Driving the method combo reuses ``_on_method_selected``, which shows the
        view, writes ``chosen_process_method`` and refreshes start readiness --
        the sheet has none of that reach on its own.
        """
        view = self._views_by_stack.get(stack_name)
        if view is None:
            return
        set_combo_value(self.method_row, view.title)
```

Confirm `set_combo_value` is already imported in `ui/window.py` with `rg -n "set_combo_value" ui/window.py | head -3`; if not, add it to the existing `from .widgets.rows import ...` block.

Then pass the handler at the `open_model_options_sheet` call (line 1129):

```python
            on_switch_method=self._on_sheet_switch_method,
```

- [ ] **Step 9: Run the applicability test**

Run: `.venv/bin/python -m unittest tests.test_model_options_sheet_applicability -v`

Expected: PASS, 8 tests (skipped without a display).

If `get_badge_number` is not readable on this libadwaita, replace those two assertions with a check that `set_badge_number` was reached — but first confirm with:

```bash
.venv/bin/python -c "import gi; gi.require_version('Adw','1'); from gi.repository import Adw; print(hasattr(Adw.ViewStackPage, 'get_badge_number'))"
```

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -20`

Expected: OK. Anything asserting on `_ensemble_banner` fails here — find it with `rg -n "_ensemble_banner" tests/` and move the assertion to the group description.

- [ ] **Step 11: Verify the whole app still starts**

Run:

```bash
UVR_SKIP_SEPARATE_WARMUP=1 .venv/bin/python -c "
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw
app = Adw.Application(application_id='org.uvr.test.smoke')
app.register()
from ui.window import MainWindow
w = MainWindow()
print('views:', [v.stack_name for v in w._views])
print('vocal split row:', type(w.vocal_split_row).__name__)
from ui.model_options.sheet import ModelOptionsSheet
s = ModelOptionsSheet(w, views=w._views, views_by_stack=w._views_by_stack, settings=w.settings, on_switch_method=w._on_sheet_switch_method)
print('sheet width:', s.dialog.get_content_width())
print('banners:', sorted(s._tab_banners))
print('OK')
"
```

Expected: prints the three view names, `VocalSplitRow`, `760`, the three banner keys, and `OK`.

Do **not** call `w.destroy()` in this script — destroying a window with no running main loop segfaults in this environment. It is a harness artifact, not a defect.

- [ ] **Step 12: Commit**

```bash
git add ui/model_options/sheet.py ui/window.py tests/test_model_options_sheet_applicability.py
git commit -m "feat(ui): mark inapplicable sheet tabs with banners and badges

Two dim Gtk.Labels are replaced by real widgets: an Adw.Banner on each
non-applicable page, and badge numbers on the ensemble tabs carrying how
many member models use that architecture.

The separation banner offers to switch architecture. The sheet cannot do
that itself, so the window supplies a callback that drives the method combo
and reuses the existing selection path.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the whole suite one more time**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5`

Expected: OK. The suite grows by roughly 75 tests (694 at plan time). The exact number depends on how many pre-existing tests get updated rather than added; what matters is zero failures and zero errors.

- [ ] **Confirm no layering violation was introduced**

Run: `rg -n "^from ui|^import ui|tkinter" core/ engines/`

Expected: no matches.

- [ ] **Confirm no new settings keys were invented**

Run:

```bash
rg -o "settings\.(get|set)\(\"[a-z_0-9]+\"" ui/option_summaries.py ui/widgets/vocal_split_row.py \
  | rg -o "\"[a-z_0-9]+\"" | tr -d '"' | sort -u > /tmp/claude-1000/-home-rudam-ultimatevocalremovergui/515bc4ca-fb96-4b5d-b4cc-dd216db27595/scratchpad/used_keys.txt
while read -r key; do
  rg -q "'$key'" bundled/constants/defaults.py || echo "MISSING FROM DEFAULT_DATA: $key"
done < /tmp/claude-1000/-home-rudam-ultimatevocalremovergui/515bc4ca-fb96-4b5d-b4cc-dd216db27595/scratchpad/used_keys.txt
```

Expected: no `MISSING FROM DEFAULT_DATA` lines.

- [ ] **Report what was NOT verified**

No agent in this environment can see the rendered UI (the Wayland sandbox has no screenshot portal). State plainly in the final report that the following remain unverified by a human and need `python -m ui`:

- whether the two columns actually look balanced on each tab
- whether the 700px stacking breakpoint triggers at a sensible window width
- whether the banner's "Switch to …" button reads clearly in place
- whether the ensemble badge numbers are legible in the inline view switcher

Do not claim any of these work.

## Out of scope

- **`ui/dialogs/utils.py:80` calls `parent.get_default_width()`**, which does not exist on `Gtk.Window` in GTK4 (`get_default_size` does). It raises `AttributeError` whenever `parent.get_width() <= 1`. Task 8 removes the sheet's two call sites, but `ui/errorlog.py:135` and `ui/download.py:409,490` still reach it. **Do not fix it in this plan** — it needs its own change with its own tests.
- The fixed-width 360px log panel.
- Search within the sheet.
- Any change to what settings mean or how engines consume them.
- Pushing to any remote.
