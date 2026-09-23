# Blueprint layout ownership

Edit fixed GTK widget trees in [`resources/ui/`](../resources/ui/). Python
controllers attach behavior and supply runtime data. Rebuild and commit the
matching resource bundle as described in [the environment guide](environment.md#blueprint-and-resource-builds).

## Shared widgets and method options

- `ui/widgets/columns.py`, `console.py`, and `log_panel.py` load the column,
  scrolling, logging, and run-control layouts. Responsive reparenting, progress,
  and log delivery remain Python behavior.
- `ui/widgets/file_chooser.py`, `dual_inputs.py`, and `format_row.py` load the
  fixed chooser and format controls. Selected paths, pair summaries, format
  values, native file dialogs, and drop callbacks are runtime data and behavior.
- `ui/widgets/vocal_split_row.py` and `stem_only.py` load fixed selection controls
  and custom-dialog shells. Eligible models, available stems, selection reducers,
  and readiness gates remain Python-owned.
- `ui/widgets/download_queue_indicator.py` loads the chip, popover, and fixed
  queue-row structure. Queue membership, progress, actions, and disposal remain
  Python-owned. `progress_ring.py` loads its overlay shell but retains Cairo
  drawing, animation, outcome icons, and numerical sizing constants.
- `ui/widgets/rows.py` configures declarative combo, switch, and scale controls.
  List models and item factories remain dynamic. Generic row factories also
  remain available to runtime callers; finite page controls belong in the page's
  Blueprint document.
- `ui/views/vr.py`, `mdx.py`, and `demucs.py` load their fixed option groups and
  controls. `base.py` owns settings routing, model providers, and refresh gates;
  compatibility row-building helpers remain available without duplicating the
  production method layouts.
- `ui/model_options/sheet.py` loads the sheet and page shells. It selects the
  supported switcher type at runtime and retains responsive allocation handling.

## Main window

`ui/window.py` loads the outer toast/banner/toolbar/overlay tree, navigation
header, primary menu, Separation banner/page shell, and fixed Separation
groups and controls. Python retains page
registration, controller-owned shared widgets, responsive reparenting, global
drop routing, and environment-dependent debugging actions.

## Run pages

- `ui/ensemble/window.py` loads the fixed ensemble page groups, action rows,
  banners, and member-picker shell. Runtime member projection, saved-preset
  operations, model membership, and field-specific settings commits remain in
  Python.
- `ui/audio_tools/window.py` loads the fixed tool pages and controls. Runtime
  model/configuration choices, tool applicability, selected files, and settings
  resynchronization remain in Python.

## Download Center

`ui/download_center.py` loads the window, toolbar, menu, filters, status/action
dock, and shared catalogue search/list/empty-state shell. Purpose navigation
selects compatible stack and switcher types in Python. Catalogue snapshots,
row membership, selection order, search projection, queue delivery, and disposal
remain with their existing controllers; dynamic rows are populated in Python.

## Preferences and auxiliary surfaces

- `ui/preferences.py` loads both fixed pages, groups, and controls. Profile
  discovery, hardware choices, platform gates, settings persistence, and
  catalogue refresh remain Python-owned.
- `ui/dialogs/model_params.py` loads the VR, MDX, MDX-C, Apollo, and change-defaults
  forms. Runtime configuration choices, carried model identity, validation,
  collection, and registry persistence remain Python-owned.
- `ui/dialogs/utils.py` loads shared dialog headers and save controls. Callers
  supply content, callbacks, and labels; shortcut and gesture controllers remain
  in Python.
- `ui/inputs.py` loads the verification window, empty state, and fixed file-row
  structure. File membership and background probing remain Python-owned.
- `ui/updates.py` and `ui/errorlog.py` load their fixed layouts. Release queries,
  error guidance, clipboard actions, logging subscriptions, and delayed delivery
  remain Python-owned.
- `ui/download.py` loads the manual-download shell and link/folder row structure.
  Catalogue groups, expanders, and URLs remain dynamic.
- `ui/audio_tools/dual_batch.py` loads its columns and dialog shell. Per-path rows,
  pair validation, ordering, and native chooser callbacks remain Python-owned.

## Native and non-layout construction

- `ui/about.py` chooses the available native About API and supplies current
  version, credits, and changelog content.
- `ui/shortcuts.py` chooses the available native shortcuts API and builds its
  entries from the central action/accelerator definitions.
- `ui/oom_dialog.py`, `ui/run_control.py`, and confirmation sites in Preferences
  and model dialogs retain native alerts with runtime text, response choices,
  and settlement callbacks. Native toasts remain in Python as well.
- `ui/widgets/file_dialogs.py` and `ui/files.py` retain native file/URI launchers,
  dialogs, filters, and initial locations.
- `ui/application.py`, `ui/notifications.py`, and `ui/resources.py` retain action
  registration, desktop notifications, and CSS/resource providers. These are
  lifecycle and platform services rather than custom widget layouts.

Optional newer libadwaita types must stay outside resources that supported older
systems load. Resource registration is display-independent; widget construction
initializes libadwaita before a builder or template expands its Adw children.

Existing `MainWindow` and Preferences subclasses retain their native root
construction and title assignment. MainWindow also owns persisted geometry and
its minimum size alongside that restore logic. A controller does not need a
second template subclass just to move those few root properties. Shared message
constants, computed subtitles, and runtime visibility remain Python inputs to
declarative controls.
