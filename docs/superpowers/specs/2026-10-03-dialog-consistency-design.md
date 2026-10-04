# Dialog consistency — design

**Status:** approved in brainstorming, awaiting spec review
**Date:** 2026-10-03
**Branch:** `dev` (implementation on a feature branch off `dev`)

## Goal

Make the app's dialogs follow one set of conventions for wording, action
placement, dismissal and sizing, with each exception named and justified.
This is the "dialog conventions" item left out of scope by the shared page
layout design (2026-10-03 UI review).

Success means:

- Every dialog title, button label and alert heading uses title case.
- Each kind of dialog (commit, live or info, pick one, alert) has one action
  layout and one dismissal behaviour; the only differences are the
  exceptions listed below.
- Every dialog uses one of three standard widths and has a minimum size.
- Tests pin all four rules, so a new dialog that breaks them fails the
  suite.

## Dialog kinds

| Kind | Meaning | Dialogs |
|---|---|---|
| **Commit** | Holds edits; one action commits them, closing discards | Input Pairs, Blend Options, Specify Model Parameters (VR, MDX, MDX-C), Apollo Model Parameters, Review Processing Plan |
| **Live / info** | Changes apply as made, or the dialog only shows information | Member Models, Model Options, Save Stems, Custom Stems, Verify Inputs, Compare Stems, run-failure dialog, Manual Downloads, Updates, Change Model Defaults, Settings, About |
| **Pick one** | Choosing an item closes the dialog | Choose Model |
| **Alert** | `Adw.AlertDialog` confirmations and prompts | The 12 alerts in the catalogue |
| **Window** | Separate resizable `Adw.Window` | Download Center, Error Log |

All commit dialogs were checked: none applies edits live. Blend Options
edits a snapshot that only Apply writes, Input Pairs only calls
`on_confirm` on Save, and the parameter forms only `collect()` on Save.

## 1. Wording

**Rule:** dialog titles, button labels and alert headings use GNOME header
capitalization (title case). Articles, short conjunctions and short
prepositions stay lowercase unless they are the first word: a, an, and,
as, at, but, by, for, in, of, on, or, the, to, with. Body text,
descriptions and row titles inside dialogs keep sentence case.

A row that opens a dialog keeps its sentence-case label (the "Blend options"
row opens "Blend Options"): the words match, only the case differs.

Changes:

- **Titles:** Model Options, Save Stems, Custom Stems, Input Pairs, Blend
  Options, Review Processing Plan, Compare Stems, Manual Downloads. The
  run-failure title becomes "‹Job› Failed" (for example "Separation
  Failed").
- **Buttons:** Check Again, Not Now, Download Missing, Export Completed,
  Retry with Smaller Segment.
- **Alert headings:** Stop Processing and Downloads?, Cancel Model
  Downloads and Quit?, Processing Has Not Stopped, GPU Out of Memory (and
  its "(Debug Mock)" variant), Replace Profile "…"?, Load Profile "…"?,
  Remove Profile?, Reset All Settings?, Download Missing Models?, Delete
  Ensemble?, Delete Stored Parameters?. Quoted names inside a heading keep
  their own spelling. `QUIT_WHILE_PROCESSING_CONFIRM` ("Stop Processing?")
  and "Save Ensemble" already comply.
- **Stop confirmation:** `STOP_PROCESS_CONFIRM`'s heading "Confirmation"
  says nothing about the action; it becomes "Stop Processing?", matching
  its Stop button and the quit variant. Its body is unchanged.

No exceptions.

## 2. Action placement

**Commit dialogs:** Cancel at the header bar's start, the suggested action
at its end, no close button. Escape cancels. This replaces today's close
button beside Save or Apply, which silently discarded edits.
`resources/ui/form-dialog-content.blp` (used by `run_blocking_dialog` for
the parameter forms) gains the Cancel button; Blend Options and Input Pairs
adopt the same header layout.

**Exception — Review Processing Plan** keeps its bottom Cancel / Start
Processing pills. It is the last step before a long run, its pill mirrors
the run card's Start Processing button that opened it, and it already has
no close button.

**Live / info dialogs:** close button only. Extra actions sit with what
they act on:

- a bottom bar for actions on the dialog's list: Verify Inputs (Add Files…,
  Verify, Remove Unreadable) and Download Center (Download);
- inline beside their subject: Change Model Defaults' Change… and Delete
  act on the selected model, the run-failure dialog's Copy Report and View
  Log act on the report, Updates' Check Again sits in its status row.

These already comply; the rule only records them.

**Pick one:** Choose Model keeps "Use This Model" as a pill on its details
page, a step inside the picker rather than a separate commit.

**Alerts:** unchanged; libadwaita owns their layout.

## 3. Dismissal

**Live / info and pick-one dialogs:** a backdrop click and Escape both
close. Choose Model, Settings and About gain backdrop close (they call
`present()` directly today and skip the shared helper).

**Commit dialogs, including Review Processing Plan:** Escape cancels; a
backdrop click does nothing, so a stray click cannot discard edits. Input
Pairs and the four parameter forms stop closing on backdrop click; Blend
Options and Review Processing Plan already behave this way.

**Alerts:** libadwaita default (Escape chooses the cancel response; the
backdrop does nothing).

**Windows:** Escape closes them, as now (`close_on_escape`).

`present_modal_dialog(dialog, parent, *, dismiss_on_backdrop=True)` gains
the keyword; commit dialogs pass `False`.

**To verify during implementation:** `_install_backdrop_dismiss` marks the
first "dimming" widget it finds and never re-attaches. If libadwaita reuses
that widget across dialogs, a later dialog's backdrop click would close the
earlier, already-closed dialog. A test opens two dialogs in turn and checks
the second one closes; if the widget is shared, the handler must close the
dialog currently presented.

## 4. Sizing

**Rule: three content widths by content.**

| Width | For | Dialogs |
|---|---|---|
| 440 | Forms, short info | Specify Model Parameters ×3, Apollo Model Parameters, Change Model Defaults, Updates, Custom Stems |
| 600 | Single-column lists and tools | Save Stems, Verify Inputs, Input Pairs, Blend Options, Review Processing Plan, Compare Stems, run-failure dialog, Manual Downloads |
| 800 | Browsers, two-column sheets | Choose Model, Member Models, Model Options |

**Rule: minimum size 360×294** (GNOME's smallest supported size) on every
`Adw.Dialog`. Choose Model keeps its 480 minimum height and Review
Processing Plan its 400, which they set so their controls and content stay
visible together.

**Rule: opening height.** Lists and browsers set a content height so they do
not open as a sliver: Choose Model, Member Models, Save Stems, Verify
Inputs, Input Pairs, Blend Options, Review Processing Plan, Compare Stems,
Manual Downloads. Forms and short info dialogs follow their content. Model
Options keeps its existing logic, which bounds its height to the window.

**Rule: never wider than the window.** The run-failure dialog's cap
(`min(width, parent width − margin)`, at least 360) moves into the shared
presentation helper and applies to every dialog, so a small window shrinks
dialogs instead of overflowing.

Fixed widths, heights and minimums live in each dialog's Blueprint; the
window cap stays in Python.

**Exceptions:** Settings (libadwaita `Adw.PreferencesDialog`, laid out at
700 sp for its search and pages) and About (`Adw.AboutDialog`) keep
libadwaita's sizing. Download Center and Error Log are resizable windows
with their own defaults and minimums.

## Out of scope

Native file choosers (`Gtk.FileDialog`), the content and layout inside each
dialog, changing Blend Options to apply live, and the review's remaining
leftovers (dot-formatted numbers).

## Testing

- **Wording:** one test reads every dialog Blueprint's `title`, the button
  labels in dialog Blueprints, the titles set in Python
  (`CHANGE_MODEL_DEFAULTS_TEXT`, `APOLLO_MODEL_PARAMETERS_TEXT`, the
  run-failure title) and every `Adw.AlertDialog` heading and response
  label, and checks title case against the lowercase-word list.
- **Actions:** commit dialogs have a Cancel button at the header start, the
  suggested action at the end and no close button; Review Processing Plan
  keeps its bottom pills.
- **Dismissal:** each dialog's presentation path matches its kind (backdrop
  close on or off); the shared-dimming check above.
- **Sizing:** every dialog Blueprint's content width is one of 440, 600,
  800 for its tier, and every `Adw.Dialog` has a minimum of at least
  360×294; the window cap shrinks a dialog presented over a narrow window.
- **Before/after screenshots:** a capture script opens every dialog in the
  catalogue (all `Adw.Dialog`s, the two windows and each alert, with
  representative content: a few inputs, a populated plan, a failed-run
  report) inside the private headless display and saves a PNG of each. It
  runs once on the current code **before any change** and again after the
  implementation, in light and dark at the default window size, plus a
  narrow window (360 wide) for the sizing rule. Images go to
  `.superpowers/dialog-screenshots/{before,after}/` (local scratch, never
  committed) with matching file names, and the implementation ends with a
  side-by-side review of every pair. The script is local scratch in the
  same directory, so the "after" run reuses it unchanged.
- **Visual check:** the after set is reviewed for clipped or squeezed
  content, wrong case and stray close buttons; anything off is fixed and
  re-captured.

## Appendix: catalogue (2026-10-03)

| Dialog | Opens from | Kind | Actions today | Close | Backdrop | Size today (min) |
|---|---|---|---|---|---|---|
| Choose Model | Separation model row | Pick one | Row click; "Use This Model" pill on details | ✓ | ✗ | 800×640 (360×480) |
| Member Models | Ensemble Member models row | Live | Checkboxes; Select All / Clear | ✓ | ✓ | 800×640 (360×480) |
| Model options | Model options row, menu | Live | Architecture tabs | ✓ | ✓ | 760 (360×294) |
| Save stems | Save stems "Choose…" | Live | Summary bottom bar | ✓ | ✓ | 620 (320×240) |
| Custom stems | Save stems → custom | Live | — | ✓ | ✓ | 400×480 (none) |
| Verify Inputs | Input header button | Live | Bottom bar: Add Files…, Verify, Remove Unreadable | ✓ | ✓ | 620 (320×240) |
| Input pairs | Audio Tools "Edit…" | Commit | Header end: Save | ✓ | ✓ | 640×520 (none) |
| Blend options | Blend options row | Commit | Header end: Apply | ✓ | ✗ | 540×620 (none) |
| Review processing plan | Start Processing | Commit | Bottom pills: Cancel, Start Processing | ✗ | ✗ | 560×600 (360×400) |
| Specify Model Parameters (×3) | Unknown model at run time | Commit | Header end: Save | ✓ | ✓ | 440 (none) |
| Apollo Model Parameters | Unknown Apollo model | Commit | Header end: Save | ✓ | ✓ | 440 (none) |
| Change Model Defaults | Model Options → Edit… | Live | Inline: Change…, Delete | ✓ | ✓ | 440 (none) |
| Compare stems | Toast after a run | Live | Header: folder, shortcuts; player bottom bar | ✓ | ✓ | 560 (none) |
| ‹Job› failed | Failed run | Info | Inline: Copy Report, View Log | ✓ | ✓ | 600 capped (none) |
| Manual downloads | Download Center | Info | Link rows | ✓ | ✓ | window width (none) |
| Updates | Menu | Info | "Check again" in a row | ✓ | ✓ | 425 (425) |
| Settings | Menu | Live | — | ✓ | default | 700 sp |
| About | Menu | Info | — | ✓ | default | libadwaita |
| Download Center | Menu | Window | Bottom bar: Download | window | Escape | 860×620 (360×440) |
| Error Log | Menu, View Log | Window | Header buttons | window | Escape | 800×560 (360×320) |

Alerts: Confirmation (stop; Cancel, Stop); Stop processing and
downloads? / Cancel model downloads and quit? / Stop Processing? (quit;
Cancel, Stop and Quit); Processing has not stopped (Wait Longer, Quit); GPU
out of memory (Export completed, Stop, Retry with smaller segment); Replace
/ Load profile "…"?, Remove profile?, Reset all settings? (Cancel + action);
Download missing models? (Not now, Download
missing); Save Ensemble (Cancel, Save); Delete ensemble? (Cancel, Delete);
Delete stored parameters? (Cancel, Delete).
