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

GTK Save stems persist the same `process.stem_focus` field. `--profile gui` inherits it; pass `--stems primary|secondary|both` when you want a positional override instead.

`--vocal-split` is still a model id. Splitter filenames stay Lead / Backing Vocals. `--main-stem` is still an ensemble pair id (`vocals_instrumental`, `karaoke`, …).

`uvr models list` / `show` JSON keeps native yaml/hash `primary_stem` keys. The human table pretty-prints known aliases.
