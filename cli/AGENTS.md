# AGENTS.md — `cli/`

The command-line front end. A presentation layer, exactly like `ui/`.

- **`cli` → `core`, never the reverse.** There are no `core` CLI trampolines;
  `uvr` is public and `python -m cli` is only an internal/testing entry point.
- **No GTK, torch, onnxruntime or `engines` at import time.** `cli/__init__.py`
  is a docstring. Heavy work stays behind core resolvers and runner start calls.
- **Named process flags are typed settings layers.** They compile to `(path,
  value)` pairs and flow through `SettingsResolver`; `--set` is the last CLI
  layer.
- **Read-only listing passes `allow_network=False` into catalogue helpers.**
  Resolving display names may otherwise fetch remote metadata.
- **Planning / validate / identity** use
  `access_policy(allow_network=False, allow_metadata_writes=False)` /
  `mdx_c_network(False)`, not `catalogue_offline()`. Downloads default online.
- **Reports are versioned.** `--report json` owns one stdout document;
  `--report jsonl` owns one event per line. Usage errors follow the selected
  report mode. Interrupts use exit 130 and `"stopped": true`.
- **Diagnostics never own stdout.** Route structured diagnostics through
  `core.debug_log`; JSON/JSONL stdout remains machine-readable. `--verbose`
  prints the effective plan and is independent from `--debug` / `--trace`.
- **Ctrl-C is cooperative then forced.** `cli.execution.run_runner_cli` owns
  signal installation and restores previous SIGINT/SIGTERM handlers in `finally`.
  `core.blocking_runner.run_blocking` captures runner exceptions and interruptions.
- **Clean defaults are the implicit profile.** GUI state is read only through
  `--profile gui`; named profiles are sparse and never write back to the GUI.
- **Models own their family.** Public IDs are `vr:`, `mdx:`, `demucs:`, or
  `apollo:` IDs; there is no public processing-method flag.
- **`--stems` is a concept, not a position.** It resolves against the model's
  route inventory (`core.stems.model_stem_routes`), so `vocals` exports vocals
  from an instrumental-primary model. Availability is diagnosed at plan time:
  an explicit CLI pick that no route provides is an `error`; the same value
  inherited via `--profile gui` is a `warning` and falls back to every viable
  output. `--stems primary|secondary|both` remains the positional override and
  writes `primary` / `secondary` (or empty for both) into `process.stem_focus`.
- **Inherited identity is never silent.** A profile-supplied primary identity
  requires TTY confirmation or `--accept-inherited`; dry-run never prompts.
- **Dry runs verify model files but have no run-side effects.** They hash and
  resolve checkpoint metadata, but do not load weights, create output, check
  heavy runtime dependencies, or start a runner.
- **CLI `run_batch` calls `JobRunner.start_resolved` once per input.** The core
  API also supports multiple planned inputs. Models
  assemble once and are reused; `run_batch` runs each planned input on its own
  staging directory and promotes it before starting the next, so a mid-batch
  death keeps what already finished. Promotion follows `--on-exists` under a
  per-output-dir `threading.Lock`. Overwrite *moves* existing destinations to
  `.{name}.uvr-overwrite.bak` until the whole unit succeeds; failure restores
  backups and returns files to staging. A `rename` collision discovered
  mid-move rolls the unit back and restarts it on one new suffix — never two.
  Failed/interrupted staging is removed. Exit 3 means partial.
- **Bench identities are explicit.** A GUI profile may supply settings, but
  never the model identity. Both dry validations finish before leg A and every
  run gets a new job-ID directory.
- Patch the owning CLI presentation boundary or public core service in tests.

## Focused verification

```bash
.venv/bin/python -m unittest discover -s tests -t . -p 'test_cli*.py' -q
```

## Command and promotion ownership

`discovery.py` is the parser/command facade. Handlers live under `commands/` by
model reads, durable model registration, catalogue transfer, ensembles, settings,
devices and completion. `model_metadata`, `ensemble_rows`, `settings_fields` and
`formatting` are shared lower providers. Tests patch the handler's actual owner;
facade import aliases do not forward patches. Shallow model list and detailed
model show retain different metadata acquisition boundaries.

`promotion_plan.py` owns immutable original entries, output associations and
suffix remapping. `promotion.py` owns the transaction: fresh occupancy checks,
no-replace publication, complete-unit retry, overwrite backups and reverse
rollback. `execution.py` retains the public compatibility imports. Per-directory
locks serialize threads; filesystem no-replace operations protect other processes.
`start_resolved` captures its own resolved settings snapshot before the worker;
callers still construct models with their intended settings.
