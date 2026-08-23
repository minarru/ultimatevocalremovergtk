# Task 4 Report: GUI and CLI display surfaces

## Status

Complete. GUI and CLI presentation adapters now prefer the exact-ID display
projection or the authoritative display already carried by a resolved model.
Canonical IDs remain the stored widget values. Refreshes reveal newly installed
models but keep a previously presented missing selection gated until the user
explicitly picks it.

## Surface audit

| Surface | Current call path audited | Result |
| --- | --- | --- |
| Primary picker | `MethodView.populate_models` -> `ModelIdentityService.records` -> `(record.id, record.display)` | Display path was already shared. Fixed refresh dropping the write gate and silently selecting a newly installed prior value. |
| Secondary and pre-process pickers | `MethodView._populate_model_combos_now` -> installed `ModelRecord` rows | Picker values and labels were already exact ID/display pairs; existing restoration gates were characterized. Collapsed summaries bypassed records, so they now resolve canonical IDs through `ModelIdentityService`. |
| Ensemble members | `EnsemblePage._rebuild_model_list` -> installed records plus `ensemble_model_list` eligibility | Labels and values were already record display/canonical ID. Fixed refresh silently checking a formerly missing member. |
| Vocal Splitter | `VocalSplitRow._populate_models_now` -> `repo.karaoke_model_list` -> installed records | Picker was already correct. Kept eligibility metadata-only and added a misleading “Karaoke” decoy regression. Routed the collapsed subtitle through the installed record display. |
| Model Test / parameters | `_change_defaults_model_config` -> exact record -> `ModelConfig(identity=record)` | Model Test output naming already carries the resolved descriptor display. Fixed the parameter dialog title fallback to prefer `model_display_label`, including when no repository remains attached. |
| Download Center | catalogue row construction in `DownloadCenterWindow` | Replaced `canonical_display_name(selection)` with an exact family/artifact projection. Search and sort now include the same displayed label while download identity stays the raw catalogue selection. |
| CLI catalogue | `ModelCatalogueService.records` | Uses the same exact catalogue projector as Download Center and reads family-scoped `meta_by_family` before the compatibility-flat metadata map. |
| Progress / OOM / logs | `_progress_detail`, `run_separator` OOM request, `model_summary_lines`, `build_separation_context` | Prefer the carried authoritative display. Pre-run log context resolves a canonical setting through `ModelIdentityService`, with legacy fallback retained. |
| Human CLI plan | `format_effective_plan` | Multi-model rows and Vocal Splitter now show `Display [canonical:id]`. |
| JSON display | `ModelRecord.to_dict`, resolved plan descriptors | Already correct: `display` is presentation and identity fields remain exact. Characterized; no production change. |
| Repository refresh | repository publication subscribers and picker-specific repaint methods | Existing single refresh publication remains unchanged. Primary, secondary, pre-process, ensemble, Vocal Splitter, and Apollo gates survive repaint; newly available rows require an explicit repick. |

## Implementation files

Production:

- `cli/job.py`
- `core/error_context.py`
- `core/model_catalogue.py`
- `core/run_loop.py`
- `core/separator_run.py`
- `ui/dialogs/model_params.py`
- `ui/download_center.py`
- `ui/ensemble/window.py`
- `ui/option_summaries.py`
- `ui/views/base.py`
- `ui/widgets/vocal_split_row.py`

Tests:

- `tests/test_cli_list_models.py`
- `tests/test_download_center_search.py`
- `tests/test_error_context.py`
- `tests/test_method_view_refresh.py`
- `tests/test_model_identity_contracts.py`
- `tests/test_model_params_identity.py`
- `tests/test_model_picker_records.py`
- `tests/test_oom_recovery.py`
- `tests/test_option_summaries.py`
- `tests/test_run_loop.py`
- `tests/test_vocal_split_row.py`

The Task 5 script, generator, test, and documentation files present in the
working tree were neither edited nor staged by Task 4.

## TDD evidence

### Initial focused RED

Command:

```text
.venv/bin/python -m unittest \
 tests.test_method_view_refresh.InstalledRecordPickerTests.test_refresh_lists_a_newly_installed_gated_primary_without_selecting_it \
 tests.test_model_picker_records.EnsemblePickerTests.test_refresh_lists_a_newly_installed_gated_member_without_selecting_it \
 tests.test_run_loop.ProgressDetailDisplayTests \
 tests.test_error_context.ErrorContextTests.test_model_summary_prefers_the_carried_identity_display \
 tests.test_model_params_identity.ChangeDefaultsIdentityTests.test_parameter_dialog_prefers_the_carried_identity_display \
 tests.test_cli_list_models.CliDisplayParityTests.test_human_ensemble_plan_lists_display_and_exact_id \
 tests.test_cli_list_models.CliDisplayParityTests.test_human_plan_uses_vocal_splitter_display \
 tests.test_model_identity_contracts.CatalogueDisplayProjectionTests -v
```

Observed: seven behavioral assertion failures exposed the primary/ensemble
refresh, runtime-label, CLI, and catalogue bypasses. The first invocation also
found one test-fixture import error; after correcting that fixture, the
catalogue assertion was a clean RED (`'1_HP-UVR' != 'HP 1'`).

Family-scoped metadata RED:

```text
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
 .venv/bin/python -m unittest \
 tests.test_model_identity_contracts.CatalogueDisplayProjectionTests.test_catalogue_projection_uses_family_split_metadata -v
```

Observed: `['1_HP-UVR', '1_HP-UVR'] != ['HP 1', '1_HP-UVR']`.

Additional adapter RED:

```text
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
 UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
 .venv/bin/python -m unittest \
 tests.test_option_summaries.SecondaryModelsSummaryTests.test_canonical_id_uses_the_installed_record_display \
 tests.test_option_summaries.VocalSplitSummaryTests.test_splitter_uses_the_installed_record_display \
 tests.test_error_context.ErrorContextTests.test_build_separation_context_prefers_installed_record_display \
 tests.test_oom_recovery.JobRunnerOomRecoveryTests.test_oom_dialog_prefers_the_carried_identity_display -v
```

Observed: the first three tests could not find a shared identity-service
adapter and the OOM request used `SCNet Tran` instead of `SCNet Transient`.
After the minimal adapters were added, the same four tests passed.

### Private GTK RED

The Download Center display and search behaviors were each run through the
required private runner before implementation:

```text
codex sandbox \
 -c 'permissions.gtk-headless.extends=":workspace"' \
 -c 'permissions.gtk-headless.description="GTK tests using private headless Wayland"' \
 -c 'permissions.gtk-headless.network.enabled=true' \
 -C "$PWD" --disable network_proxy -P gtk-headless \
 /home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- \
 env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
 .venv/bin/python -m unittest <focused-test> -v
```

Observed private sockets and failures:

- `/tmp/codex-gtk.UergiF/codex-gtk`: Download row displayed `1_HP-UVR`, expected `HP 1`.
- `/tmp/codex-gtk.FIRTho/codex-gtk`: searching for the projected display returned false.

No host `DISPLAY`, `WAYLAND_DISPLAY`, or session bus was supplied to these
runs. The inline profile was necessary because the local Codex configuration
does not define `gtk-headless`; it still extends the managed workspace sandbox,
disables `network_proxy`, and delegates display/session creation to the
repository-approved private runner.

## Final verification

Non-GTK regression command:

```text
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
 UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
 .venv/bin/python -m unittest \
 tests.test_model_identity_contracts tests.test_run_loop \
 tests.test_error_context tests.test_oom_recovery \
 tests.test_model_params_identity tests.test_option_summaries \
 tests.test_cli_list_models -v
```

Output: `Ran 166 tests in 1.285s` / `OK` / exit 0.

Final private GTK command:

```text
codex sandbox \
 -c 'permissions.gtk-headless.extends=":workspace"' \
 -c 'permissions.gtk-headless.description="GTK tests using private headless Wayland"' \
 -c 'permissions.gtk-headless.network.enabled=true' \
 -C "$PWD" --disable network_proxy -P gtk-headless \
 /home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- \
 env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
 .venv/bin/python -m unittest \
 tests.test_method_view_refresh tests.test_model_picker_records \
 tests.test_download_center_search tests.test_vocal_split_row \
 tests.test_model_params_identity -v
```

Output/evidence:

```text
Private Wayland socket: /tmp/codex-gtk.i6tVSI/codex-gtk
Private D-Bus: unix:path=/tmp/dbus-xDfBMAnk9b,...
Ran 84 tests in 0.209s
OK
runner exit 0
```

The portal emitted expected teardown warnings about unavailable FUSE/PipeWire
and losing the private compositor after the tests. They did not affect the
runner result.

Static and whitespace verification:

```text
.venv/bin/basedpyright <all Task 4 production and test files>
git diff --check
.venv/bin/ruff check --select E9,F63,F7,F82 <all Task 4 production and test files>
```

Output: `0 errors, 0 warnings, 0 notes`; `git diff --check` clean; Ruff
`All checks passed!`.

## Self-review

- Exact IDs remain row values and settings payloads; displays are never fed
  back into identity resolution.
- Catalogue metadata is family-scoped, avoiding collisions when identical
  selection text exists in two architecture catalogues.
- Existing write gates stay sticky only while their stored value is unchanged;
  explicit user selection or an external settings replacement clears them.
- Ensemble preservation handles malformed/unhashable legacy values without
  attempting set membership on them.
- Vocal Splitter eligibility still comes exclusively from repository metadata;
  display wording cannot admit a model.
- Model Test and JSON paths required characterization only, so no unnecessary
  production changes were made there.
- No catalogue refresh or publication code was changed, preserving the one
  repository refresh contract.

No unresolved Task 4 concern remains. Repository-wide formatting debt was not
expanded or mechanically rewritten; focused syntax/error lint, type checking,
and whitespace checks are clean.

## Fix Round 1

This round addresses both Important review findings. It supersedes the earlier
write-gate preservation wording above: a gated auxiliary-model value is now
removed from effective GUI settings at the flush/persist boundary. This
intentionally sacrifices the stale remembered selection so a later install
cannot activate it without an explicit repick.

### Surface and plan audit

- Secondary and Demucs pre-process combo gates now flush the model key to
  `NO_MODEL` and their corresponding activation flag to `False`.
- Vocal Splitter now flushes its gated model to `NO_MODEL` and disables the
  splitter while still deriving picker eligibility exclusively from repository
  karaoke/BV metadata.
- Ensemble persistence drops gated or unchecked members while retaining valid,
  explicitly checked members. A resolved-plan regression covers a three-member
  selection where the newly installed gated member remains unselected and the
  other two members remain active.
- Primary separation and Apollo restoration already block plan construction
  through `has_model()` / `_apollo_blocked_reason` while their gated combos show
  `CHOOSE_MODEL`; their existing private-GTK regressions remain green, so no
  production change was made to those paths.
- Ensemble human error context now resolves exact selected-model IDs through
  `ModelIdentityService` when the live GUI supplies its repository. It falls
  back to the exact stored value when lookup fails and never mutates the
  canonical settings payload.

### Files changed in Fix Round 1

- `ui/views/base.py`
- `ui/widgets/vocal_split_row.py`
- `ui/ensemble/window.py`
- `ui/run_control.py`
- `core/error_context.py`
- `tests/test_gui_gated_plans.py`
- `tests/test_model_picker_records.py`
- `tests/test_vocal_split_row.py`
- `tests/test_error_context.py`
- `tests/test_run_control.py`
- this report

### RED evidence

Resolved-plan regressions were first run against the preservation behavior:

```text
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
 UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
 .venv/bin/python -m unittest \
 tests.test_gui_gated_plans \
 tests.test_error_context.ErrorContextTests.test_ensemble_error_log_uses_displays_without_mutating_exact_ids -v
```

Observed before implementation: four failures showed the secondary,
pre-process, Vocal Splitter, and third ensemble member still active in the
resolved plan; the error-context test errored because
`build_ensemble_context()` did not accept a repository. The corrected fixtures
still failed on the production behavior, rather than on test setup.

The live-caller regression was also proven independently by temporarily
removing the repository argument after adding the test and using the private
runner. Private socket `/tmp/codex-gtk.ihqrdD/codex-gtk` produced:

```text
['mdx:first', 'vr:second'] != ['Friendly First', 'Friendly Second']
Ran 1 test
FAILED (failures=1)
runner exit 1
```

### GREEN evidence

The same focused non-GTK command passed after the minimal implementation:

```text
Ran 5 tests
OK
```

The live-caller test passed through private socket
`/tmp/codex-gtk.3IOTEI/codex-gtk`, with a private D-Bus, `Ran 1 test`, `OK`,
and runner exit 0.

Covering non-GTK verification:

```text
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
 UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
 .venv/bin/python -m unittest \
 tests.test_gui_gated_plans tests.test_error_context \
 tests.test_ensemble_flush_settings tests.test_identity_planning \
 tests.test_saved_ensembles -v
```

Output: `Ran 70 tests in 0.707s` / `OK (skipped=2)` / exit 0. The two GTK
tests skipped without a display were included in the private run below.

Final private GTK command (not piped):

```text
codex sandbox \
 -c 'permissions.gtk-headless.extends=":workspace"' \
 -c 'permissions.gtk-headless.description="GTK tests using private headless Wayland"' \
 -c 'permissions.gtk-headless.network.enabled=true' \
 -C "$PWD" --disable network_proxy -P gtk-headless \
 /home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- \
 env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
 .venv/bin/python -m unittest \
 tests.test_method_view_refresh tests.test_model_picker_records \
 tests.test_vocal_split_row tests.test_apollo_picker_write_gate \
 tests.test_saved_ensembles.SavedEnsembleWarningGtkTests \
 tests.test_run_control.EnsembleErrorContextSnapshotTests
```

Private-display evidence and output:

```text
Private Wayland socket: /tmp/codex-gtk.yYCDk4/codex-gtk
Private D-Bus: unix:path=/tmp/dbus-sjaBqe2GgZ,...
Ran 78 tests in 0.266s
OK
runner exit 0
```

Expected portal teardown warnings about unavailable FUSE/PipeWire and losing
the private compositor did not affect the successful runner result. No host
display or session bus was passed to the test command.

Static and whitespace verification:

```text
.venv/bin/basedpyright core/error_context.py ui/run_control.py \
 ui/views/base.py ui/widgets/vocal_split_row.py ui/ensemble/window.py \
 tests/test_gui_gated_plans.py tests/test_error_context.py \
 tests/test_run_control.py tests/test_model_picker_records.py \
 tests/test_vocal_split_row.py
.venv/bin/ruff check --select E9,F63,F7,F82 <same files>
git diff --check
```

Output: `0 errors, 0 warnings, 0 notes`; Ruff `All checks passed!`;
`git diff --check` clean; all commands exited 0.

### Fix Round 1 self-review

- The plan tests exercise real `JobResolver` CONFIG plans and dependency maps,
  not widget state alone.
- Exact canonical IDs remain in settings and plan identity payloads; only the
  copied human error-context model list is projected to display text.
- Error-context display lookup is optional and preserves the prior exact-value
  fallback when no repository is supplied or resolution fails.
- Refresh still reveals newly installed entries without selecting them, and
  valid ensemble checks survive removal of the gated member.
- No new core gating schema was introduced, and no Task 5 catalogue or audit
  file was edited for this round.
