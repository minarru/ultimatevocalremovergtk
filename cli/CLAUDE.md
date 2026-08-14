# CLAUDE.md — `cli/`

The headless front end. A presentation layer, exactly like `ui/`.

- **`cli` → `core`, never the reverse.** `core/cli.py` and `core/__main__.py`
  are trampolines that import `cli.main` lazily *inside a function body*; that
  is the only `core → cli` reference in the tree and it must stay lazy.
- **No GTK, torch, onnxruntime or `engines` at import time.** `cli/__init__.py`
  is a docstring. Heavy work stays behind `core.headless_run`.
- **Named flags never become `build_settings` kwargs.** They compile to
  `(path, value)` pairs in `process_flags.py` and go through
  `core.settings.access.apply_settings_overrides`, the same validated path as
  `--set`.
- **Read-only commands default to offline** via `offline.catalogue_offline()`.
  Resolving display names otherwise fetches two catalogues with 30s timeouts.
  `--online` does not clear `UVR_DISABLE_*` already set in the environment.
- **`--json` failures still emit one document** via `reporting.fail()`.
  Interrupts use exit 130 and `"stopped": true`.
- **Ctrl-C is cooperative then forced.** `_run_job` must not re-raise
  `KeyboardInterrupt`. Restore the previous SIGINT/SIGTERM handlers in `finally`.
- **Ensemble member source is explicit.** `--ensemble` (saved or curated) or
  `--model`/`--models`. Ineligible members warn; they do not abort.
- Patch `cli.<module>.<name>` in tests, never `core.cli.*`.
