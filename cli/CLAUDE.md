# CLAUDE.md — `cli/`

The command-line front end. A presentation layer, exactly like `ui/`.

- **`cli` → `core`, never the reverse.** There are no `core` CLI trampolines;
  `uvr` is public and `python -m cli` is only an internal/testing entry point.
- **No GTK, torch, onnxruntime or `engines` at import time.** `cli/__init__.py`
  is a docstring. Heavy work stays behind core resolvers and runner start calls.
- **Named process flags are typed settings layers.** They compile to `(path,
  value)` pairs and flow through `SettingsResolver`; `--set` is the last CLI
  layer.
- **Read-only listing passes `allow_network=False` into catalogue helpers;**
  `core.offline.catalogue_offline` is a deprecated no-op. Resolving display
  names otherwise fetches two catalogues with 30s timeouts.
- **Planning / validate / dry-run** use `mdx_c_network(False)` /
  `ensure_mdx_c_config(..., allow_network=False)`, not `catalogue_offline()`.
- **Reports are versioned.** `--report json` owns one stdout document;
  `--report jsonl` owns one event per line. Usage errors follow the selected
  report mode. Interrupts use exit 130.
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
- **Batch outputs are staged.** Successful inputs are promoted according to
  `--on-exists`; failed/interrupted staging is removed. Exit 3 means partial.
- **Bench identities are explicit.** A GUI profile may supply settings, but
  never the model identity. Both dry validations finish before leg A and every
  run gets a new job-ID directory.
- Patch the owning CLI presentation boundary or public core service in tests.
