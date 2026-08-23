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
