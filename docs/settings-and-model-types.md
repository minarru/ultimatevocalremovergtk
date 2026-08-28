# Settings and model types

`settings.json` is the current nested, typed settings document. New code uses
`Settings`, `ModelConfig`, `assemble_model`, and `ProcessData`; the removed
legacy public names `SettingsModel`, `ModelData`, and `assemble_model_data`
are not compatibility APIs.

## Module layout

| Path | Role |
|------|------|
| `core/types/enums.py` | `Stem`, `EnsembleAlgorithm`, `ProcessMethod`, `SaveFormat` (`str, Enum`; values are current English labels) |
| `core/types/settings_enums.py` | Closed combo vocabularies (wav/mp3/flac, denoise, colour, audio tools, diagnostics, …) |
| `core/settings/model.py` | Nested `Settings` dataclasses, including plain-string `EnsembleSettings.main_stem` and persistent `DiagnosticsSettings` |
| `core/settings/defaults.py` | Nested defaults and `SETTINGS_SCHEMA_VERSION` (currently 5) |
| `core/settings/coerce.py` | JSON and flat-dict coercion, including pair/mode normalization |
| `core/settings/flat_map.py` | Legacy flat-key to nested-field bridge for older input only |
| `core/settings/io.py` | `settings.json` load/save and one-shot `data.pkl` import |
| `core/stem_pairs.py` | Exact `ensemble.main_stem` validation and display choices |
| `bundled/model_stem_manifest.json` | Data-defined pair roles and namespaced pair IDs |
| `core/model_config/` | `ModelConfig` hierarchy and `assemble_model` |

## Current JSON shape

```json
{
  "schema_version": 5,
  "process": {
    "device": null,
    "semitone_shift": 0.0,
    "wav_type": "PCM_16"
  },
  "vr": { "batch_size": null },
  "mdx": {
    "overlap_mdx": null,
    "chunks": null,
    "compensate": null,
    "overlap_mdx23": 8
  },
  "demucs": { "segment": null },
  "ensemble": {
    "main_stem": "pair.vocals_instrumental",
    "type": "Max Spec/Min Spec",
    "selected_models": [],
    "chosen_ensemble": "Choose Ensemble"
  },
  "audio_tools": {},
  "ui": { "color_scheme": "auto" },
  "diagnostics": {
    "level": "errors",
    "include_sensitive": false
  }
}
```

Nested JSON is the persistence format; flat key access is a legacy bridge, not
the persistence API.

## Schema and migration behavior

The runtime writes schema 5. Schema 4 added persistent diagnostic level and
sensitive-detail policy under `diagnostics`. Schema 5 made
`ensemble.main_stem` a reviewed namespaced semantic ID and deliberately
requires a repick from every older schema.

`ensemble.main_stem` is a plain string, normalized by
`core.stem_pairs.normalize_stem_pair_id` against the manifest-defined pair IDs
and the two mode IDs:

- `pair.vocals_instrumental`
- `pair.karaoke`
- `pair.backing_vocals`
- `pair.center_side`
- `mode.four_stem`
- `mode.multi_stem`

The empty string means “Choose Stem Pair.” An unknown ID from a schema-5 file
also normalizes to empty and records a warning. When a file predates schema 5,
loading clears `ensemble.main_stem`, records a repick warning, and writes the
current schema on the next save; it does not retain aliases for old display or
unnamespaced values.

Coercion runs over every payload before `Settings.from_json_dict` stamps the
current schema version. `Default`/`Auto` sentinels become JSON `null` for typed
optional fields; chunks `"Full"` persists as `"full"`; numeric strings such as
`semitone_shift`, `overlap_mdx23`, and Apollo spins load as numbers. Unknown
closed-enum values fail soft to their field defaults.

## Persistence rules

1. Writes go only to `settings.json` (atomic `.tmp` plus replace).
2. Load order is `settings.json`, otherwise a one-shot `data.pkl` import that
   writes JSON and renames the pickle to `data.pkl.bak`.
3. Profiles use the same coerce/serialize path and accept legacy flat profile
   dictionaries once.
4. Stored model references are strict `family:basename` values; malformed or
   unavailable values remain stored until the user repicks them.

## Invariants

- Enum `.value` strings stay current UI labels (`Stem.VOCALS == "Vocals"`).
- `use_gpu` remains `bool` end to end (never `0` or `-1`).
- Ensemble keys (`selected_models`, `main_stem`, `type`, and
  `chosen_ensemble`) are first-class settings fields.
- Paths, model tags, and open stem lists remain strings.
- Export toggles (`normalization`, `match_mix_level`,
  `prevent_export_clipping`, and `amplification_threshold`) live under
  `process`.
