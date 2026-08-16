# CLAUDE.md — `cli/`

The command-line front end. A presentation layer, exactly like `ui/`.

- **`cli` → `core`, never the reverse.** There are no `core` CLI trampolines;
  `uvr` is public and `python -m cli` is only an internal/testing entry point.
- **No GTK, torch, onnxruntime or `engines` at import time.** `cli/__init__.py`
  is a docstring. Heavy work stays behind core resolvers and runner start calls.
- **Named process flags are typed settings layers.** They compile to `(path,
  value)` pairs and flow through `SettingsResolver`; `--set` is the last CLI
  layer.
- **Read-only listing passes `allow_network=False` into catalogue helpers.**
  Resolving display names otherwise fetches two catalogues with 30s timeouts.
- **Planning / validate / identity** use
  `access_policy(allow_network=False, allow_metadata_writes=False)` /
  `mdx_c_network(False)`, not `catalogue_offline()`. Downloads default online.
- **Reports are versioned.** `--report json` owns one stdout document;
  `--report jsonl` owns one event per line. Usage errors follow the selected
  report mode. Interrupts use exit 130 and `"stopped": true`.
- **Ctrl-C is cooperative then forced.** `_run_job` must not re-raise
  `KeyboardInterrupt`. Restore the previous SIGINT/SIGTERM handlers in `finally`.
- **Clean defaults are the implicit profile.** GUI state is read only through
  `--profile gui`; named profiles are sparse and never write back to the GUI.
- **Models own their family.** Public IDs are `vr:`, `mdx:`, or `demucs:` IDs;
  there is no public processing-method flag.
- **Inherited identity is never silent.** A profile-supplied primary identity
  requires TTY confirmation or `--accept-inherited`; dry-run never prompts.
- **Dry runs verify model files but have no run-side effects.** They hash and
  resolve checkpoint metadata, but do not load weights, create output, check
  heavy runtime dependencies, or start a runner.
- **`JobRunner.start_resolved` is the batch entry.** It assembles once; CLI
  still stages and promotes. Successful inputs are promoted according to
  `--on-exists` under a per-output-dir `threading.Lock`. Overwrite copies
  existing destinations to `.{name}.uvr-overwrite.bak` until the whole unit
  succeeds; failure restores backups and returns files to staging.
  Failed/interrupted staging is removed. Exit 3 means partial.
- **Bench identities are explicit.** A GUI profile may supply settings, but
  never the model identity. Both dry validations finish before leg A and every
  run gets a new job-ID directory.
- Patch the owning CLI presentation boundary or public core service in tests.
