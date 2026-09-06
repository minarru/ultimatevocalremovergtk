# Maintenance scripts

Three model-maintenance command entry points under `scripts/`, plus `model_tool_support.py` and the `scripts/catalogue/` collection/rendering package. None are part of the app.

- **`scripts/*` is gitignored behind an allowlist.** A new script needs its own
  `!scripts/<name>.py` line in [.gitignore](../.gitignore), or `git add` refuses it and the
  file never lands.
- **One shared low-level module.** [scripts/model_tool_support.py](../scripts/model_tool_support.py)
  owns validated HTTP ranges, checkpoint headers and tail hashes, catalogue target
  resolution and cache identity. `model_probe.py` and the generator's optional
  stem-confidence audit both import from it; verdicts, reporting and architecture construction
  stay in their owning commands. Range reads validate the 206 and `Content-Range` and raise `RangeError`
  rather than returning whatever the server sent.
- **The catalogue generator publishes one validated bundle from one snapshot.** The unified manifest, catalogue Markdown, intent/display/stem TSVs, and IR are rendered and validated in memory from the same post-deduplication collection before any target is replaced; never hand-edit a generated Markdown/TSV. The generator refuses to publish a degraded run. Exit codes are distinct:
  `0` wrote/up to date, `1` drift (`--check`), `2` this run's data is too degraded to
  judge. A cold cache yields a fraction of the catalogue, so without the guard a partial
  run replaces a good 7,000-line document. `--allow-degraded` overrides.
- **`--check` and `--summary` are read-only.** Publication YAML evidence comes only from
  checked-in seed configs or the URL-keyed generator cache; `FetchPolicy.allow_cache_writes`
  gates persistence there, and no generator path writes runtime model config storage.
  `--summary` prints to stdout and writes nothing.
- **Drift means the catalogue changed, not that time passed.** `--check` compares canonical
  forms with the volatile header lines (`Generated:`, provenance, cache ages) stripped.
- **Ephemeral catalogue caches live under `CACHE_DIR`**, separate from the checked-in
  unified authority and runtime/user state. Source/config entries are keyed by URL rather
  than basename (two models can both ship a `config.yaml`) and use TTL plus stale-while-
  revalidate. The schema-2 stem-evidence cache keeps exact last-known-good parsed evidence
  and its error/staleness state; a failed refresh never erases usable evidence. `--refresh`
  forces a refetch of Download Center coordinator sources (upstream, Politrees, extras,
  mvsepless) and supplements; `--offline` is strictly cache-only and may serve stale data.
- **The `.ir.json` sidecar is tied to its document by SHA-256** and is gitignored. The
  publication guard reads its previous entry count from it only when that digest matches,
  falling back to the document — a stale sidecar must not lower the guard's floor.
- **`model_sweep.main()` asserts the parent stays torch-free.** An in-process test must hide
  `torch` from `sys.modules` for the call rather than weaken the assert; another test module
  importing torch first trips it, so failures depend on test ordering.
- **`--timeout` does not reach composite jobs.** They are their own group (`SweepJob.composite`,
  not `kind`, and not identifiable from the timeout they carry) and take `--composite-timeout`.
- **The optional stem-confidence audit caches successful hashes indefinitely and failures never.**
  Checkpoint tails are immutable once published; caching a failure would let one bad network
  day poison every later report. Run it through
  `generate_models_catalogue.py --audit-stem-confidence`; `--only`/`--limit` narrow a run,
  `--no-cache` re-fetches, and `--offline` requires the hash cache.
- **VR architecture sizes have one definition**, `VR_ARCH_SIZES` / `VR_5_1_ARCH_SIZES` in
  [ml/vr_network/nets.py](../ml/vr_network/nets.py). `model_probe.py` imports them lazily —
  that module pulls in torch, and the probe must stay importable without it.
- **`build_mdx_c_model` / `filter_init_kwargs`** ([engines/mdx_c.py](../engines/mdx_c.py)) are
  public engine-layer API, built against from the engine and the probe.
- Script artifacts publish through `core.json_store.write_text_atomic` / `write_json_atomic`:
  a failed write must not truncate a checked-in document, and the sweep parent treats an
  unreadable child `result.json` as a classified job failure rather than crashing.
