# Command-line interface

`uvr` is the headless front end for Ultimate Vocal Remover. This is the
complete task-oriented CLI guide. [Models and stems](models.md) owns model,
catalogue, and architecture details; [Environment and developer
configuration](environment.md) owns runtime paths, variables, and diagnostics.

## Getting started and command discovery

The installer exposes this checkout's launcher as `uvr` when
`~/.local/bin/uvr` is available. From a checkout, `./uvr` always works and
selects that checkout's virtual environment.

```bash
uvr --help
uvr models list
uvr devices list
uvr separate /path/to/song.wav -o /path/to/stems \
  --model mdx:MODEL_BASENAME --dry-run
```

Paths under `/path/to/`, uppercase values such as `MODEL_BASENAME`, and
`CATALOGUE_ENTRY` below are placeholders. Replace them before running a
command. Obtain installed model IDs from `uvr models list`; do not copy a
placeholder model ID literally. Every command and subcommand also has
`--help`.

## Finding and downloading models

`uvr models list` reports the installed model inventory. Use `--family` to
narrow it and `--all-known` to include catalogue-only records.

```bash
uvr models list --family mdx
uvr models list --all-known
uvr models catalog --family mdx --query karaoke
uvr models show mdx:MODEL_BASENAME
uvr models download "CATALOGUE_ENTRY"
```

`uvr models catalog` searches downloadable entries. `uvr models download`
accepts an exact `catalog:` ID, selectable name, or display name, followed by
a unique-substring fallback. Installed-model lookup is deliberately stricter;
see [Canonical model IDs](#canonical-model-ids).

The two catalogue commands share one command-scoped snapshot. An online command
refreshes remote sources; if a source fails, the command can retain its last
good mixed-age data and report the snapshot as stale or partial. It fails when
there is no usable snapshot or no requested entry. Add `--offline` to use
cached catalogue data without refreshing remote sources.

See [Models and stems](models.md) for catalogue sources, support status, and
architecture-specific requirements.

## Separation, ensembles, and Audio Tools

Use `separate` for one model. Use `ensemble` with a saved or curated
ensemble, or supply at least two explicit members. An ad-hoc ensemble also
requires a reviewed `--main-stem` pair or mode ID.

```bash
uvr separate /path/to/song.wav -o /path/to/stems \
  --model mdx:MODEL_BASENAME

uvr ensemble /path/to/song.wav -o /path/to/stems \
  --model mdx:FIRST_MODEL_BASENAME \
  --model demucs:SECOND_MODEL_BASENAME \
  --main-stem pair.vocals_instrumental

uvr ensembles list
uvr ensemble /path/to/song.wav -o /path/to/stems \
  --ensemble "SAVED_OR_CURATED_NAME"
```

The GUI Audio Tools are available under `uvr audio`: `inspect`, `ensemble`,
`stretch`, `pitch`, `align`, `match`, and Apollo `restore`.

```bash
uvr audio inspect /path/to/song.wav
uvr audio stretch /path/to/song.wav -o /path/to/processed --rate 1.1 --dry-run
uvr audio restore /path/to/song.wav -o /path/to/processed \
  --model apollo:MODEL_BASENAME
uvr audio align -o /path/to/processed \
  --pair /path/to/first.wav /path/to/reference.wav \
  --pair /path/to/second.wav /path/to/reference.wav
```

Single-input tools accept files or directories. `align` and `match` take
repeatable `--pair A B` arguments. Processing Audio Tools share the separation
commands' profiles, reports, validation, dry runs, staging, collision policies,
manifests, and replay checks. Validate one with `uvr validate audio TOOL ...`.

## Stem selection

`--stems` selects the outputs to save. Concept names select that concept even
when it is not the checkpoint's primary output; positional names follow the
model's native pair layout.

| Token | Meaning |
| --- | --- |
| `vocals` | The Vocals concept |
| `instrumental` | The Instrumental concept |
| `bass`, `drums`, `other` | The corresponding MUSDB stem |
| `primary`, `secondary` | The model's positional pair sides |
| `both`, `all` | Every stem; clears `process.stem_focus` |

For example, `--stems vocals` on an instrumental-primary model saves vocals,
not the primary side. `--set process.stem_focus=vocals` makes the same
exclusive selection. Multi-stem MDX-C models resolve `bass`, `drums`,
`other`, and `vocals` through native YAML source keys. `instrumental` is
the derived vocals complement; **Combine Stems** changes how it is calculated,
not its identity or filename.

For four-stem and multi-stem ensembles, selection filters final outputs only.
Members still generate the sources needed to combine them, and a multi-stem
final output needs at least two contributing members. An unavailable explicit
CLI selection is an error. The same value inherited from a GUI or named profile
warns and falls back to all viable outputs.

GTK **Save stems** and the CLI share `process.stem_focus`. `--profile gui`
inherits it; use `--stems primary`, `--stems secondary`, or `--stems both`
for a positional CLI override. `--vocal-split` takes a canonical model ID,
not a Boolean flag; its output filenames remain **Lead Vocals** and **Backing
Vocals**.

Accepted `--main-stem` IDs are:

- `pair.vocals_instrumental`
- `pair.karaoke`
- `pair.backing_vocals`
- `pair.center_side`
- `mode.four_stem`
- `mode.multi_stem`

## Canonical model IDs

Runtime model IDs are exact `family:basename` values in the `vr`, `mdx`,
`demucs`, and `apollo` namespaces. Processing commands, ensemble members,
`models show`, and `models configure` use exact canonical IDs; there is no
display-name, bare-basename, or substring fallback. Obtain an installed ID from
`uvr models list` rather than guessing it.

Apollo restoration follows the same rule. Obtain its exact ID with
`uvr models list --family apollo`, then pass that `apollo:basename` value to
`uvr audio restore --model`.

Register an unknown checkpoint before trying to process with it:

```bash
uvr models register /path/to/model.ckpt --family mdx \
  --config /path/to/model.json
```

Registration copies the checkpoint into the managed model tree and saves
validated configuration. Local metadata overrides catalogue metadata. For
Demucs, `--family demucs --config /path/to/model.json` writes the version,
source layout, and artifacts to the versioned Demucs registry. Reset that
metadata with:

```bash
uvr models configure demucs:MODEL_BASENAME --reset
```

`models list` and `models show` JSON retain native YAML/hash
`primary_stem` keys; the human table prettifies recognized aliases.
`models show` JSON includes `id`, `family`, `basename`, `display`,
`backend_name`, artifact filenames, `identity_complete`, and
`identity_error`. `backend_name` is the legacy engine value; there is no
`engine_name` field.

## Profiles and settings precedence

CLI jobs start from typed application defaults; they do not read GUI settings
implicitly. Select `--profile gui`, a named sparse profile, or a profile JSON
path explicitly. Named flags and `--set section.field=value` apply only to
the current invocation and never write GUI settings.

```bash
uvr settings profile create fast-gpu \
  --model mdx:MODEL_BASENAME \
  --set process.autocast=true --set mdx.segment_size=256
uvr separate /path/to/song.wav -o /path/to/stems --profile fast-gpu
uvr settings explain mdx.segment_size --profile fast-gpu
```

When a profile supplies a model, ensemble preset, or member list, a real
interactive run previews the effective plan and asks
`Use these settings? [y/N]`. Machine-readable and non-TTY runs must add
`--accept-inherited`. A dry run previews inherited identity without prompting.

A portable sparse profile has `schema_version` 1. Its identity is separate
from the flat settings map and uses one of `model`, `ensemble`, or
`members`:

```json
{
  "schema_version": 1,
  "name": "fast-gpu",
  "model": "mdx:MODEL_BASENAME",
  "ensemble": null,
  "members": [],
  "settings": {
    "process.autocast": true,
    "mdx.segment_size": 256
  }
}
```

Settings resolve in this order: built-in defaults, model-native automatic
values, ensemble preset, profile, named CLI flags, `--set`, environment, then
derived runtime values. `UVR_AUTOCAST` is the current environment override,
so it wins over `--autocast`. Use `uvr settings show`,
`uvr settings explain`, and `uvr settings validate` to inspect effective
settings and their sources.

## Validation and dry runs

```bash
uvr separate /path/to/song.wav -o /path/to/stems \
  --model mdx:MODEL_BASENAME --dry-run
uvr validate separate /path/to/song.wav -o /path/to/stems \
  --model mdx:MODEL_BASENAME --level runtime
uvr models validate mdx:MODEL_BASENAME
```

`--dry-run` verifies input paths, checkpoint existence and hash, model
configuration, and planned outputs. It does not load weights, import inference
engines, create output directories, or start a runner.

Validation levels are `config`, `model`, `runtime`, and `load`.
`load` loads the checkpoint through the applicable runtime without running
inference. Processing plans and validation may download an exact missing MDX-C
YAML configuration. Add `--offline` to `separate`, `ensemble`, processing
Audio Tools, `run`, or `models validate` to prevent that fetch; a missing
configuration then becomes an error. Catalogue commands also accept
`--offline`, as described above.

`uvr models list`, including `--all-known`, uses installed and cached metadata
without fetching catalogue or configuration data. `uvr models show` may fetch
a missing configuration and has no `--offline` option. For a no-network
detailed configuration check, use
`uvr models validate mdx:MODEL_BASENAME --offline`.

## Batch processing, collision handling, and manifests

Commands accepting inputs also accept directories. Use `--recursive` and a
repeatable `--include GLOB`; inputs are sorted and deduplicated.

```bash
uvr separate /path/to/music -o /path/to/stems --recursive \
  --include '*.flac' --model mdx:MODEL_BASENAME --on-exists rename
uvr separate /path/to/song.wav -o /path/to/stems \
  --model mdx:MODEL_BASENAME --manifest
uvr run /path/to/stems/uvr-manifest-JOB_ID.json -o /path/to/replay
```

Outputs stage per input and are promoted only after success, serialized by a
per-output-directory lock. `--on-exists` accepts `fail` (the default),
`overwrite`, `rename`, or `skip`. With `overwrite`, existing
destinations move to `.{name}.uvr-overwrite.bak` until the whole unit
succeeds. A failure restores the backup and returns files to staging.

Batches continue after an input failure by default; use `--fail-fast` to stop
at the first failure. `separate` and `ensemble` also accept the explicit
`--continue-on-error` spelling for scripts. Processing Audio Tools keep the
same continue-by-default behavior but expose only `--fail-fast`. `--manifest`
writes under the output directory; `--manifest-out PATH` selects an explicit
location.

Separation, ensemble, and Audio Tools manifests use schema 3. They record
effective settings, provenance, canonical-ID `model_dependencies`, a
`model_identity_digest` with a `sha256:` prefix, model hashes, inputs,
outputs, backend, and outcomes. Replay rejects a changed model dependency. If
the dependency IDs are unchanged but a checkpoint hash or identity digest
changed, replay requires `--allow-model-change`. Benchmark manifests remain
schema 1.

For a batch, models assemble once. The runner processes and promotes one input
at a time before beginning the next.

## JSON and JSONL reports and exit codes

Use `--report human|json|jsonl` to select stdout ownership. `json` writes
exactly one versioned result document. `jsonl` writes versioned `planned`,
`started`, `progress`, `input_finished`, and `finished` events, one
object per line. Every JSONL event includes the schema version and job ID.
Engine chatter and structured diagnostics stay off machine-readable stdout.

```json
{
  "schema_version": 1,
  "job_id": "UUID",
  "ok": true,
  "status": "success",
  "command": "separate",
  "plan": {},
  "inputs": []
}
```

Successful results add the effective plan, per-input outcomes, timings, and
output paths. Failures use the same envelope with `ok: false` and an
`error` object. An interrupted machine result has `ok: false`,
`status: "failed"`, `stopped: true`, and exit code 130.

| Exit code | Meaning |
| --- | --- |
| 0 | Success or skipped output |
| 1 | Complete runtime failure |
| 2 | Usage, configuration, validation, or confirmation failure |
| 3 | Partial batch success |
| 130 | Interrupted |

`--quiet` suppresses progress and engine chatter; `--verbose` prints the
effective plan for a real job. `--debug` and `--trace` select the separate
structured diagnostic stream. See
[Logging and diagnostics](environment.md#logging-and-diagnostics) for levels,
privacy, and log locations.

## Benchmarking and shell completion

```bash
uvr bench /path/to/song.wav -o /path/to/bench \
  --model mdx:MODEL_BASENAME \
  --a-env UVR_AUTOCAST=0 --b-env UVR_AUTOCAST=1 \
  --a-set mdx.segment_size=256 --b-set mdx.segment_size=512
uvr completion bash
```

Both benchmark legs validate before leg A starts and run in a fresh job-ID
directory. Use per-leg model, profile, environment, and setting flags for
broader comparisons. `--keep-outputs always|failure|never` controls retained
results. GPU kernels may not be bitwise deterministic; the CLI has no
`--seed` option until an engine exposes controllable randomness.

`uvr completion` supports `bash`, `zsh`, and `fish`.

## Migration from the experimental CLI

The pre-release CLI intentionally does not ship compatibility shims for its
earlier experimental surface.

| Earlier experimental interface | Current interface |
| --- | --- |
| `python -m core` / `python -m core.cli` | Removed; use `uvr` |
| `python -m cli` | Internal/testing only; public scripts use `uvr` |
| `bench-ab` | `uvr bench` |
| `list-models` | `uvr models list` |
| `--json` | `--report json` |
| `--json-out` | `--manifest-out` for job manifests |
| `--print-settings` | `--verbose`, `--dry-run`, or `uvr settings show` |
| `--method` | Removed; the canonical model ID determines the family |
| `--cpu` / `--gpu` | `--device auto\|cpu\|cuda:N\|mps\|directml:N` |

Removed Python headless helpers are replaced by the public resolved-job and
blocking-runner APIs in `core`; no import trampoline remains.
