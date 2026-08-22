# Task 9 report

Model assembly now resolves canonical IDs through the identity index and passes
complete `ModelRecord` values into `ModelConfig`. Configurations retain the
canonical ID, display label, backend name, and artifacts while leaving settings
unchanged, and model paths are derived from the primary artifact rather than
inverting display text.

Nested secondary, pre-process, and vocal-splitter configuration uses strict
identity lookup. An enabled missing model now raises `ValueError` instead of
being silently omitted.

TDD evidence:

- RED: the new assembly tests failed because `ModelConfig` lacked canonical
  identity fields, and the active missing-secondary test failed because
  `ValueError` was swallowed.
- GREEN: the Task 9 verification suite passes all 71 tests.

Verification:

- `.venv/bin/python -m unittest tests.test_identity_planning tests.test_core_model_data tests.test_mdx_model_path tests.test_job_plan_topology -v`
  — 71 tests passed.
- `.venv/bin/python -m basedpyright core/model_config`
  — 0 errors, 0 warnings, 0 notes.
- `git diff --check`
  — clean.
