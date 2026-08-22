# Task 10 report

## Status

Implemented Task 10 on `feat/model-id-improvement` from base `9e273a5`.

- `ModelConfig.get_demucs_model_data()` now uses `DemucsSpec` metadata instead
  of parsing display text.
- Added the six-source Demucs layout constant and assignment.
- Dry model resolution normalizes the VR UI process label to the VR engine
  architecture and preserves canonical identity records.
- Demucs dry-path coverage now resolves through canonical IDs.
- Existing plan-native segment behavior remains covered and unchanged.

## TDD evidence

The planned test command was run before implementation and failed in the
expected four places: VR architecture normalization, v1 Demucs assignment,
misleading display independence, and six-source stem count.

After implementation:

```text
.venv/bin/python -m unittest tests.test_identity_planning tests.test_demucs_name_resolution tests.test_job_plan_native_values -v
Ran 34 tests
OK
```

Touched-file type checking:

```text
.venv/bin/python -m basedpyright core/model_config/config.py core/model_repository.py bundled/constants/stems.py tests/test_identity_planning.py tests/test_demucs_name_resolution.py
0 errors, 0 warnings, 0 notes
```

`git diff --check` also passed.

## Additional full-suite observation

An additional, non-plan full-suite run completed 2,324 tests with three
pre-existing failures outside the Task 10 paths:

- `BatchExecutionTests.test_run_batch_uses_start_resolved_with_stage_export_paths`
  assembles the non-canonical sentinel `Choose Model`.
- Two `IdentityServiceTests` migration cases fail to resolve `Model A`.

All three reproduce independently. The requested Task 10 modules are green.

## Commit

`feat: assign Demucs version and layout from DemucsSpec`

No push was performed.
