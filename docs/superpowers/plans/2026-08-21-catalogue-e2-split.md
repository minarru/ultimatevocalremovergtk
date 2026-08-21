# E2: Split catalogue collector from renderer

> Mechanical file split. No behaviour change. Approval gate before implementation.

**Goal:** Split the 1,874-line catalogue generator into collect/render modules under `scripts/catalogue/`, leaving `generate_models_catalogue.py` as the CLI for argparse, publication policy, and writes.

**Context:** E1 (IR), E3 (`--summary`), and E4 (`_collect_entries` is the one collection path) landed in #73. This is the remaining Phase E item from the scripts-audit follow-up.

## Layout

```
scripts/catalogue/__init__.py     empty package marker, no barrel re-exports
scripts/catalogue/collect.py      snapshot → entries + IR
scripts/catalogue/render.py       entries → Markdown / summary / TSV text
scripts/generate_models_catalogue.py   argparse, publication guard, writes
```

`.gitignore` (parent `scripts/*` hides unlisted files):

```
!scripts/catalogue/
!scripts/catalogue/__init__.py
!scripts/catalogue/collect.py
!scripts/catalogue/render.py
```

`pyrightconfig.json` already includes `scripts` and lists it in `extraPaths`.

## Move map

**collect.py:** `CommunityRef`, `CatalogueContext`, `ModelEntry`, `FetchPolicy`, snapshot/payload helpers, cache fetch (`_cache_path` through `_scan_weight_hashes`), yaml/hash/community inference, `_parse_catalogue_entry` through `_entries_from_snapshot`, `collect_entries` (today `_collect_entries`), `build_ir`, `IR_SCHEMA_VERSION`, `_ir_path_for`, `_document_digest`.

**render.py:** `_md_table`, `_render`, `render_summary_report`, `_summary_health_warning`, `_provenance_lines`, `_cache_age_text`, `_reference_tsv_text`, `_canonical_for_diff`, `_text_matches`, `_VOLATILE_PREFIXES`.

**CLI:** `_parse_args`, `_policy_for`, `PublicationVerdict`, `_publication_verdict`, `_previous_entry_count`, `_DEGRADED_DROP_RATIO`, `main`.

Public names to drop the `_` on while moving (already used as API): `ModelEntry`, `FetchPolicy`, `collect_entries`, `build_ir`, `render_summary_report`. Other helpers stay private in their new module.

## Imports

CLI inserts `scripts/` on `sys.path` (same as tests) and does `from catalogue.collect import ...` / `from catalogue.render import ...`. User command stays `python scripts/generate_models_catalogue.py`.

Tests currently `import generate_models_catalogue as catalogue` and poke `_ui_note`, `_finalize_entry`, `_fetch_cached`, `main`, etc. Retarget those imports at the owning module. Do not re-export privates from the CLI to keep the alias working.

## Out of scope

- Stem-semantics overlay
- Further splitting collect.py
- Changing `--summary` / `--check` / IR sidecar contracts

## Verification

```bash
.venv/bin/python -m unittest tests.test_generate_models_catalogue -v
.venv/bin/python -m basedpyright scripts/generate_models_catalogue.py scripts/catalogue tests/test_generate_models_catalogue.py
python scripts/generate_models_catalogue.py --help
python scripts/generate_models_catalogue.py --check
```

One commit after green tests.
