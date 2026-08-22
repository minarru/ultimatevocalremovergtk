# CLI

`uvr` is the headless front end. `uvr --help` lists commands; each subcommand has its own `--help`. This page covers stem selection, which GTK and the CLI now share through `settings.json`.

## `--stems`

```bash
uvr separate song.wav -o /tmp/out --model mdx:Model --stems vocals
uvr separate song.wav -o /tmp/out --model mdx:Model --stems primary
uvr separate song.wav -o /tmp/out --profile gui --accept-inherited
```

Concept names select that stem even when it is not the checkpoint primary:

| Token | Meaning |
| --- | --- |
| `vocals` | The Vocals concept (`process.stem_focus=Vocals`) |
| `instrumental` | The Instrumental concept |
| `bass`, `drums`, `other` | That MUSDB stem |
| `primary`, `secondary` | Positional sides of the pair; **clears** `process.stem_focus` |
| `both` / `all` | Every stem; clears `process.stem_focus` |

`--stems vocals` on an instrumental-primary 2-stem model exports vocals, not the primary. `--set process.stem_focus=vocals` is the same exclusive pick (`vocals` ≡ `Vocals`).

Multi-stem MDX-C models resolve `bass`, `drums`, `other`, and `vocals` against
their native YAML source keys. `instrumental` is a derived vocals complement;
the **Combine Stems** setting changes whether that audio is summed from the
remaining sources or obtained by subtraction, but does not change its identity
or filename.

For four- and multi-stem ensembles, stem selection filters final ensemble
outputs only. Member models still produce the sources required for combining,
and a multi-stem final output requires at least two contributing members.
An unavailable explicit CLI selection is an error. An inherited GUI/profile
selection warns and falls back to all viable outputs.

GTK Save stems persist the same `process.stem_focus` field. `--profile gui` inherits it; pass `--stems primary|secondary|both` when you want a positional override instead.

`--vocal-split` is still a model id. Splitter filenames stay Lead / Backing Vocals. `--main-stem` is still an ensemble pair id (`vocals_instrumental`, `karaoke`, …).

## Models

`uvr models list` prints **installed** checkpoints (filesystem inventory). Catalogue-only records that are not installed are omitted unless you pass `--all-known`.

`uvr models catalog` / `download` share one command-scoped catalogue coordinator and close it on exit. If a live refresh fails, they continue with the last good mixed-age snapshot and print a stale/partial warning (human stderr, `catalogue_status` in JSONL). They fail only when no usable snapshot or requested entry exists.

`uvr models list` / `show` JSON keeps native yaml/hash `primary_stem` keys. The human table pretty-prints known aliases.

`uvr models show` JSON reports the canonical identity fields from `ModelRecord.to_dict()` — `id`, `family`, `basename`, `display`, `backend_name` (the value the legacy engine layer consumes; there is no `engine_name` field) — plus artifact filenames and `identity_complete`/`identity_error`. Model identity lookup for `--model`, `models show`, and `models configure` is exact `family:basename`; only `uvr models download` keeps a catalogue-only fuzzy match (exact catalogue ID, selectable, or display, then a unique substring) — see [models.md](models.md).
