# Settings and model types

Design note for the typed settings / `ModelConfig` rewrite (`rewrite/typed-settings-model`).

## Cutover status

The typed API cutover landed in Phase 6. New code imports `Settings`,
`ModelConfig`, `assemble_model`, and `ProcessData`; the legacy public
`SettingsModel`, `ModelData`, and `assemble_model_data` names were removed.
`data.pkl` remains read-only migration input, while all settings writes use
`settings.json`.

## Module layout

| Path | Role |
|------|------|
| `core/types/enums.py` | `Stem`, `EnsembleAlgorithm`, `ProcessMethod`, `SaveFormat` (`str, Enum`; values = current English labels) |
| `core/settings/model.py` | Nested `Settings` dataclasses |
| `core/settings/defaults.py` | Nested defaults + `SETTINGS_SCHEMA_VERSION` |
| `core/settings/coerce.py` | JSON / flat-dict coerce helpers |
| `core/settings/flat_map.py` | Legacy flat key ↔ nested field map (pickle / old profiles) |
| `core/settings/io.py` | `settings.json` load/save + one-shot `data.pkl` import |
| `core/settings/__init__.py` | Public `Settings` API |
| `core/process_data.py` | `ProcessData` run payload |
| `core/model_config/` | `ModelConfig` hierarchy + `assemble_model` |

## JSON document shape

```json
{
  "schema_version": 2,
  "process": {},
  "vr": {},
  "mdx": {},
  "demucs": {},
  "ensemble": {
    "main_stem": "choose",
    "type": "Max Spec/Min Spec",
    "selected_models": [],
    "chosen_ensemble": "Choose Ensemble"
  },
  "audio_tools": {},
  "ui": {}
}
```

Nested on disk. Flat key access is not the persistence API.

**v2 breaking change:** `ensemble.main_stem` persists stable :class:`~core.stems.EnsemblePair` ids only (`choose`, `vocals_instrumental`, `karaoke`, `other`, `drums`, `bass`, `four_stem`, `multi_stem`). Legacy display strings (e.g. `Vocals/Instrumental`) are not migrated — they coerce to `choose` and the pair must be re-selected once.

## Persistence rules

1. Writes go only to `settings.json` (atomic `.tmp` + replace).
2. Load order: `settings.json` → else import `data.pkl` → write JSON → rename pickle to `data.pkl.bak`.
3. Profiles use the same coerce/serialize path as `settings.json` (accept legacy flat profile dicts once).

## Locked decisions

- Enum `.value` strings stay current UI labels (`Stem.VOCALS == "Vocals"`).
- Sentinels `DEF_OPT` / `AUTO_SELECT` / `"Default"` become `None` or `"auto"` in typed fields.
- `use_gpu: bool` end-to-end (no `0`/`-1`).
- Ensemble keys (`selected_models`, `main_stem`, `type`, `chosen_ensemble`) are first-class in the schema; `main_stem` is an `EnsemblePair` id (not a UI label).
- Export toggles (`normalization`, `match_mix_level`, `prevent_export_clipping`, `amplification_threshold`) live under `process`.
